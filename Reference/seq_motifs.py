#!/usr/bin/env python
# Some of the following fuctions are from https://github.com/davek44/Basset; some are modified.
from optparse import OptionParser
import copy, os, pdb, random, shutil, subprocess, time
import h5py
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
import seaborn as sns
from sklearn import preprocessing
import sys

basedir = os.path.split(os.path.dirname(os.path.abspath(__file__)))[0]
sys.path.append(basedir)
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

plt.style.use('ggplot')
matplotlib.rcParams.update({'font.family': 'Times New Roman', 'font.size': 18, 'font.weight': 'light', 'figure.dpi': 350})

# import dna_io

################################################################################
# basset_motifs.py
#
# Collect statistics and make plots to explore the first convolution layer
# of the given model using the given sequences.
################################################################################

# weblogo_opts = '-X NO -Y NO --errorbars NO --fineprint ""'
weblogo_opts = '-X NO --fineprint "" --resolution "350" --format "PNG"'
weblogo_opts += ' -C "#CB2026" A A'
weblogo_opts += ' -C "#34459C" C C'
weblogo_opts += ' -C "#FBB116" G G'
weblogo_opts += ' -C "#0C8040" T T'
weblogo_opts += ' -C "#0C8040" U U'

reverse_mapping = {
    'A': 'A',
    'C': 'C',
    'G': 'G',
    'T': 'U'
}


def load_data(path):
    """
        Load data matrices from the specified folder.
    """

    data = dict()

    data["Y"] = np.loadtxt(gzip.open(os.path.join(path,
                                                  "matrix_Response.tab.gz")),
                           skiprows=1)


def get_motif_proteins(meme_db_file):
    ''' Hash motif_id's to protein names using the MEME DB file '''
    motif_protein = {}
    for line in open(meme_db_file):
        a = line.split()
        if len(a) > 0 and a[0] == 'MOTIF':
            if a[2][0] == '(':
                motif_protein[a[1]] = a[2][1:a[2].find(')')]
            else:
                motif_protein[a[1]] = a[2]
    return motif_protein


def info_content(pwm, transpose=False, bg_gc=0.415):
    ''' Compute PWM information content.
    In the original analysis, I used a bg_gc=0.5. For any
    future analysis, I ought to switch to the true hg19
    value of 0.415.
    '''
    pseudoc = 1e-9

    if transpose:
        pwm = np.transpose(pwm)

    bg_pwm = [1 - bg_gc, bg_gc, bg_gc, 1 - bg_gc]

    ic = 0
    for i in range(pwm.shape[0]):
        for j in range(4):
            # ic += 0.5 + pwm[i][j]*np.log2(pseudoc+pwm[i][j])
            ic += -bg_pwm[j] * np.log2(bg_pwm[j]) + pwm[i][j] * np.log2(pseudoc + pwm[i][j])

    return ic


def make_filter_pwm(filter_fasta):
    ''' Make a PWM for this filter from its top hits '''

    nts = {'A': 0, 'C': 1, 'G': 2, 'U': 3}
    pwm_counts = []
    nsites = 4  # pseudocounts
    for line in open(filter_fasta):
        if line[0] != '>':
            seq = line.rstrip()
            nsites += 1
            if len(pwm_counts) == 0:
                # initialize with the length
                for i in range(len(seq)):
                    pwm_counts.append(np.array([1.0] * 4))

            # count
            for i in range(len(seq)):
                try:
                    pwm_counts[i][nts[seq[i]]] += 1
                except KeyError:
                    pwm_counts[i] += np.array([0.25] * 4)

    # normalize
    pwm_freqs = []
    for i in range(len(pwm_counts)):
        pwm_freqs.append([pwm_counts[i][j] / float(nsites) for j in range(4)])

    return np.array(pwm_freqs), nsites - 4


def meme_add(meme_out, f, filter_pwm, nsites, trim_filters=False):
    ''' Print a filter to the growing MEME file
    Attrs:
        meme_out : open file
        f (int) : filter index #
        filter_pwm (array) : filter PWM array
        nsites (int) : number of filter sites
    '''
    if not trim_filters:
        ic_start = 0
        ic_end = filter_pwm.shape[0] - 1
    else:
        ic_t = 0.2

        # trim PWM of uninformative prefix
        ic_start = 0
        while ic_start < filter_pwm.shape[0] and info_content(filter_pwm[ic_start:ic_start + 1]) < ic_t:
            ic_start += 1

        # trim PWM of uninformative suffix
        ic_end = filter_pwm.shape[0] - 1
        while ic_end >= 0 and info_content(filter_pwm[ic_end:ic_end + 1]) < ic_t:
            ic_end -= 1

    if ic_start < ic_end:
        print('MOTIF filter%d' % f, file=meme_out)
        print('letter-probability matrix: alength= 4 w= %d nsites= %d' % (ic_end - ic_start + 1, nsites), file=meme_out)

        for i in range(ic_start, ic_end + 1):
            print('%.4f %.4f %.4f %.4f' % tuple(filter_pwm[i]), file=meme_out)
        print('', file=meme_out)


def meme_intro(meme_file, seqs):
    ''' Open MEME motif format file and print intro
    Attrs:
        meme_file (str) : filename
        seqs [str] : list of strings for obtaining background freqs
    Returns:
        mem_out : open MEME file
    '''
    # clearly we are using cDNA, so an customizable change is made here.
    # we need to use 'U' otherwise tomtom will tell us it's an error
    nts = {'A': 0, 'C': 1, 'G': 2, 'T': 3}

    # count
    nt_counts = [1] * 4
    for i in range(len(seqs)):
        for nt in seqs[i]:
            try:
                nt_counts[nts[nt]] += 1
            except KeyError:
                # print('unexpected:', nt)
                pass

    # normalize
    nt_sum = float(sum(nt_counts))
    nt_freqs = [nt_counts[i] / nt_sum for i in range(4)]

    # open file for writing
    meme_out = open(meme_file, 'w')

    # print intro material
    print('MEME version 4', file=meme_out)
    print('', file=meme_out)
    print('ALPHABET= ACGU', file=meme_out)
    print('', file=meme_out)
    print('Background letter frequencies:', file=meme_out)
    print('A %.4f C %.4f G %.4f U %.4f' % tuple(nt_freqs), file=meme_out)
    print('', file=meme_out)

    return meme_out


def name_filters(num_filters, tomtom_file, meme_db_file):
    ''' Name the filters using Tomtom matches.
    Attrs:
        num_filters (int) : total number of filters
        tomtom_file (str) : filename of Tomtom output table.
        meme_db_file (str) : filename of MEME db
    Returns:
        filter_names [str] :
    '''
    # name by number
    filter_names = ['f%d' % fi for fi in range(num_filters)]

    # name by protein
    if tomtom_file is not None and meme_db_file is not None:
        motif_protein = get_motif_proteins(meme_db_file)

        # hash motifs and q-value's by filter
        filter_motifs = {}

        tt_in = open(tomtom_file)
        tt_in.readline()
        for line in tt_in:
            a = line.split()
            fi = int(a[0][6:])
            motif_id = a[1]
            qval = float(a[5])

            filter_motifs.setdefault(fi, []).append((qval, motif_id))

        tt_in.close()

        # assign filter's best match
        for fi in filter_motifs:
            top_motif = sorted(filter_motifs[fi])[0][1]
            filter_names[fi] += '_%s' % motif_protein[top_motif]

    return np.array(filter_names)


################################################################################
# plot_target_corr
#
# Plot a clustered heatmap of correlations between filter activations and
# targets.
#
# Input
#  filter_outs:
#  filter_names:
#  target_names:
#  out_pdf:
################################################################################
def plot_target_corr(filter_outs, seq_targets, filter_names, target_names, out_pdf, seq_op='mean'):
    num_seqs = filter_outs.shape[0]
    num_targets = len(target_names)

    if seq_op == 'mean':
        filter_outs_seq = filter_outs.mean(axis=2)
    else:
        filter_outs_seq = filter_outs.max(axis=2)

    # std is sequence by filter.
    filter_seqs_std = filter_outs_seq.std(axis=0)
    filter_outs_seq = filter_outs_seq[:, filter_seqs_std > 0]
    filter_names_live = filter_names[filter_seqs_std > 0]

    filter_target_cors = np.zeros((len(filter_names_live), num_targets))
    for fi in range(len(filter_names_live)):
        for ti in range(num_targets):
            cor, p = spearmanr(filter_outs_seq[:, fi], seq_targets[:num_seqs, ti])
            filter_target_cors[fi, ti] = cor

    cor_df = pd.DataFrame(filter_target_cors, index=filter_names_live, columns=target_names)

    sns.set(font_scale=0.3)
    plt.figure()
    sns.clustermap(cor_df, cmap='BrBG', center=0, figsize=(8, 10))
    plt.savefig(out_pdf)
    plt.close()


################################################################################
# plot_filter_seq_heat
#
# Plot a clustered heatmap of filter activations in
#
# Input
#  param_matrix: np.array of the filter's parameter matrix
#  out_pdf:
################################################################################
def plot_filter_seq_heat(filter_outs, y_train, out_pdf, whiten=True, drop_dead=True):
    # compute filter output means per sequence
    filter_seqs = filter_outs.mean(axis=2)

    # whiten
    if whiten:
        filter_seqs = preprocessing.scale(filter_seqs)

    # transpose
    filter_seqs = np.transpose(filter_seqs)
    # shape: (32, 1024)
    if drop_dead:
        filter_stds = filter_seqs.std(axis=1)
        filter_seqs = filter_seqs[filter_stds > 0]

    # downsample sequences
    seqs_i = np.random.randint(0, filter_seqs.shape[1], 1024)

    hmin = np.percentile(filter_seqs[:, seqs_i], 0.1)
    hmax = np.percentile(filter_seqs[:, seqs_i], 99.9)

    locations = ['cytoplasm', 'insolubles', 'membrane', 'nuclear']

    '''classifiy'''
    y_train_ = list()
    for label in y_train:
        mode = np.argmax(label)
        y_train_.append(locations[mode])
    y_train = np.array(y_train_)[seqs_i]

    sns.set(font_scale=0.8, font="Times New Roman")

    plt.figure(figsize=(10, 10))

    '''column colors'''
    colors = [(0.9, 0.14799999999999996, 0.09999999999999998),
              (0.4520000000000001, 0.9, 0.09999999999999998),
              (0.09999999999999998, 0.8519999999999998, 0.9),
              (0.5479999999999997, 0.09999999999999998, 0.9)]
    lut = dict(zip(set(y_train), colors))
    col_colors = pd.DataFrame(y_train)[0].map(lut)
    g = sns.clustermap(filter_seqs[:, seqs_i], row_cluster=True, col_cluster=True, linewidths=0, figsize=(9,9),
                       xticklabels=False, vmin=hmin, vmax=hmax, cmap='YlGnBu', col_colors=[col_colors], metric='cosine')
    '''re-ordered'''
    # print(y_train[g.dendrogram_col.reordered_ind])

    for label in locations:
        g.ax_col_dendrogram.bar(0, 0, color=lut[label],
                                label=label, linewidth=0)
        g.ax_col_dendrogram.legend(bbox_to_anchor=(0.8, 0.9), bbox_transform=plt.gcf().transFigure, ncol=4)

    g.cax.set_position([.08, .2, .03, .45])
    plt.savefig(out_pdf, dpi=350)
    # out_png = out_pdf[:-2] + 'ng'
    # plt.savefig(out_png, dpi=300)
    plt.close()


################################################################################
# plot_filter_seq_heat
#
# Plot a clustered heatmap of filter activations in sequence segments.
#
# Mean doesn't work well for the smaller segments for some reason, but taking
# the max looks OK. Still, similar motifs don't cluster quite as well as you
# might expect.
#
# Input
#  filter_outs
################################################################################
def plot_filter_seg_heat(filter_outs, out_pdf, whiten=True, drop_dead=True):
    b = filter_outs.shape[0]
    f = filter_outs.shape[1]
    l = filter_outs.shape[2]

    # s = 5
    s = 13
    while l / float(s) - (l / s) > 0:
        s += 1
    print('%d segments of length %d' % (s, l / s))

    # split into multiple segments
    filter_outs_seg = np.reshape(filter_outs, (b, f, s, int(l / s)))

    # mean across the segments
    filter_outs_mean = filter_outs_seg.max(axis=3)

    # break each segment into a new instance
    filter_seqs = np.reshape(np.swapaxes(filter_outs_mean, 2, 1), (s * b, f))

    # whiten
    if whiten:
        filter_seqs = preprocessing.scale(filter_seqs)

    # transpose
    filter_seqs = np.transpose(filter_seqs)

    if drop_dead:
        filter_stds = filter_seqs.std(axis=1)
        filter_seqs = filter_seqs[filter_stds > 0]

    # downsample sequences
    seqs_i = np.random.randint(0, filter_seqs.shape[1], 500)

    hmin = np.percentile(filter_seqs[:, seqs_i], 0.1)
    hmax = np.percentile(filter_seqs[:, seqs_i], 99.9)

    sns.set(font_scale=0.3)
    if whiten:
        dist = 'euclidean'
    else:
        dist = 'cosine'

    plt.figure()
    sns.clustermap(filter_seqs[:, seqs_i], metric=dist, row_cluster=True, col_cluster=True, linewidths=0,
                   xticklabels=False, vmin=hmin, vmax=hmax, cmap='YlGnBu')
    plt.savefig(out_pdf)
    # out_png = out_pdf[:-2] + 'ng'
    # plt.savefig(out_png, dpi=300)
    plt.close()


################################################################################
# filter_motif
#
# Collapse the filter parameter matrix to a single DNA motif.
#
# Input
#  param_matrix: np.array of the filter's parameter matrix
#  out_pdf:
################################################################################
def filter_motif(param_matrix):
    nts = 'ACGU'

    motif_list = []
    for v in range(param_matrix.shape[1]):
        max_n = 0
        for n in range(1, 4):
            if param_matrix[n, v] > param_matrix[max_n, v]:
                max_n = n

        if param_matrix[max_n, v] > 0:
            motif_list.append(nts[max_n])
        else:
            motif_list.append('N')

    return ''.join(motif_list)


################################################################################
# filter_possum
#
# Write a Possum-style motif
#
# Input
#  param_matrix: np.array of the filter's parameter matrix
#  out_pdf:
################################################################################
def filter_possum(param_matrix, motif_id, possum_file, trim_filters=False, mult=200):
    # possible trim
    trim_start = 0
    trim_end = param_matrix.shape[1] - 1
    trim_t = 0.3
    if trim_filters:
        # trim PWM of uninformative prefix
        while trim_start < param_matrix.shape[1] and np.max(param_matrix[:, trim_start]) - np.min(
                param_matrix[:, trim_start]) < trim_t:
            trim_start += 1

        # trim PWM of uninformative suffix
        while trim_end >= 0 and np.max(param_matrix[:, trim_end]) - np.min(param_matrix[:, trim_end]) < trim_t:
            trim_end -= 1

    if trim_start < trim_end:
        possum_out = open(possum_file, 'w')
        print('BEGIN GROUP', file=possum_out)
        print('BEGIN FLOAT', file=possum_out)
        print('ID %s' % motif_id, file=possum_out)
        print('AP DNA', file=possum_out)
        print('LE %d' % (trim_end + 1 - trim_start), file=possum_out)
        for ci in range(trim_start, trim_end + 1):
            print('MA %s' % ' '.join(['%.2f' % (mult * n) for n in param_matrix[:, ci]]), file=possum_out)
        print('END', file=possum_out)
        print('END', file=possum_out)

        possum_out.close()


################################################################################
# plot_filter_heat
#
# Plot a heatmap of the filter's parameters.
#
# Input
#  param_matrix: np.array of the filter's parameter matrix
#  out_pdf:
################################################################################
def plot_filter_heat(param_matrix, out_pdf):
    param_range = abs(param_matrix).max()

    sns.set(font_scale=2)
    plt.figure(figsize=(param_matrix.shape[1], 4))
    sns.heatmap(param_matrix, cmap='PRGn', linewidths=0.2, vmin=-param_range, vmax=param_range)
    ax = plt.gca()
    ax.set_xticklabels(range(1, param_matrix.shape[1] + 1))
    ax.set_yticklabels('ACGT', rotation='horizontal')  # , size=10)
    plt.savefig(out_pdf)
    plt.close()


################################################################################
# plot_filter_logo
#
# Plot a weblogo of the filter's occurrences
#
# Input
#  param_matrix: np.array of the filter's parameter matrix
#  out_pdf:
# weblogo -X NO -Y NO --errorbars NO --fineprint ""  -C "#CB2026" A A -C "#34459C" C C -C "#FBB116" G G -C "#0C8040" T T <filter1_logo.fa >filter1.eps
################################################################################
def plot_filter_logo(filter_outs, filter_size, seqs, out_prefix, raw_t=0, maxpct_t=None):
    # acgt = 'ACGT'
    if maxpct_t:
        all_outs = np.ravel(filter_outs)
        all_outs_mean = all_outs.mean()
        all_outs_norm = all_outs - all_outs_mean
        raw_t = maxpct_t * all_outs_norm.max() + all_outs_mean

    # print fasta file of positive outputs
    filter_fasta_out = open('%s.fa' % out_prefix, 'w')
    filter_count = 0
    # iter over samples
    for i in range(filter_outs.shape[0]):
        # iter ans entire sequence
        for j in range(filter_outs.shape[1]):
            if filter_outs[i, j] > raw_t:
                kmer = seqs[i][j:j + filter_size]
                # TODO check this out
                # kmer = seqs[i][j-4:j-4+filter_size]
                if 'UNK' in kmer:
                    continue
                if len(kmer) < filter_size:
                    continue
                print('>%d_%d' % (i, j), file=filter_fasta_out)
                # converting back to mRNA from cDNA
                print("".join([reverse_mapping[c] for c in kmer]), file=filter_fasta_out)
                # filter_fasta_out.write('>{}_{}\n'.format(i, j))
                # filter_fasta_out.write(kmer)
                # filter_fasta_out.write('\n')
                filter_count += 1
    filter_fasta_out.close()
    print('plot logo')
    # make weblogo
    if filter_count > 0:
        weblogo_cmd = 'weblogo %s < %s.fa > %s.png' % (weblogo_opts, out_prefix, out_prefix)
        subprocess.call(weblogo_cmd, shell=True)


################################################################################
# plot_score_density
#
# Plot the score density and print to the stats table.
#
# Input
#  param_matrix: np.array of the filter's parameter matrix
#  out_pdf:
################################################################################
def plot_score_density(f_scores, out_pdf):
    sns.set(font_scale=1.3)
    plt.figure()
    sns.distplot(f_scores, kde=False)
    plt.xlabel('ReLU output')
    plt.savefig(out_pdf)
    plt.close()

    return f_scores.mean(), f_scores.std()
