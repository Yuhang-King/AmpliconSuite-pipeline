from collections import defaultdict
import os

from intervaltree import IntervalTree, Interval


# takes list of tuples (chrom, start, end, cn)
def compute_cn_median(cnlist, armlen):
    cnsum = sum([x[2]-x[1] for x in cnlist])
    if cnsum < 0.5 * armlen:
        return 2.0

    halfn = cnsum/2.0
    scns = sorted(cnlist, key=lambda x: x[3])
    rt = 0
    ccn = 0
    for x in scns:
        ccn = x[3]
        rt += (x[2] - x[1])
        if rt >= halfn:
            break

    return ccn


def read_bed(ifname, keepdat=False):
    beddict = defaultdict(IntervalTree)
    with open(ifname) as infile:
        for line in infile:
            line = line.rstrip()
            if line:
                fields = line.rsplit()
                s, e = int(fields[1]), int(fields[2])
                if e - s == 0:
                    print("Size 0 interval found. Skipping: " + line)
                    continue

                if keepdat:
                    beddict[fields[0]].addi(s, e, tuple(fields[3:]))
                else:
                    beddict[fields[0]].addi(s, e)

    return beddict


# read regions to split on/filter into dictionary of interval trees, where keys are chromosomes
def read_gain_regions(ref):
    AA_DATA_REPO = os.environ["AA_DATA_REPO"] + "/" + ref + "/"
    fdict = {}
    with open(AA_DATA_REPO + "file_list.txt") as infile:
        for line in infile:
            line = line.rstrip()
            if line:
                fields = line.rsplit()
                fdict[fields[0]] = fields[1]

    grf = AA_DATA_REPO + fdict["conserved_regions_filename"]
    gain_regions = read_bed(grf)

    return gain_regions


# take CNV calls (as bed?) - have to update to not do CNV_GAIN
#input bed file, centromere_dict
#output: path of prefiltered bed file
def prefilter_bed(bedfile, ref, centromere_dict, chr_sizes, cngain, outdir):
    # interval to arm lookup
    region_ivald = defaultdict(IntervalTree)
    for key, value in chr_sizes.items():
        try:
            cent_tup = centromere_dict[key]
            region_ivald[key].addi(0, int(cent_tup[0]), key + "p")
            region_ivald[key].addi(int(cent_tup[1]), int(value), key + "q")

        # handle mitochondrial contig or other things (like viral genomes)
        except KeyError:
            region_ivald[key].addi(0, int(value), key)

    # store cnv calls per arm
    arm2cns = defaultdict(list)
    arm2lens = {}
    with open(bedfile) as infile:
        for line in infile:
            fields = line.rstrip().rsplit("\t")
            c, s, e = fields[0], int(fields[1]), int(fields[2]) + 1
            cn = float(fields[-1])
            a = region_ivald[c][(s + e)//2]
            if not a:
                a = region_ivald[c][s:e]
            if a:
                carm_interval = a.pop()
                carm = carm_interval.data
                arm2cns[carm].append((c, s, e, cn))
                arm2lens[carm] = carm_interval.end - carm_interval.begin

            else:
                print("Warning: could not match " + c + ":" + str(s) + "-" + str(e) + " to a known chromosome arm!")

    cn_filt_entries = []
    for a in sorted(arm2cns.keys()):
        # compute the median CN of the arm
        init_cns = arm2cns[a]
        med_cn = compute_cn_median(init_cns, arm2lens[a])
        for x in init_cns:
            ccg = cngain
            if x[2] - x[1] > 5000000:
                ccg *= 1.5

            if x[3] > med_cn + ccg - 2:
                cn_filt_entries.append(x)

    gain_regions = read_gain_regions(ref)
    # now remove regions based on filter regions
    final_filt_entries = []
    for x in cn_filt_entries:
        cit = IntervalTree()
        cit.addi(x[1], x[2])
        bi = gain_regions[x[0]]
        for y in bi:
            cit.slice(y.begin)
            cit.slice(y.end)

        for p in sorted(cit):
            final_filt_entries.append((x[0], p[0], p[1], x[3]))

    bname = outdir + "/" + bedfile.rsplit("/")[-1].rsplit(".bed")[0] + "_pre_filtered.bed"
    with open(bname, 'w') as outfile:
        for entry in final_filt_entries:
            outfile.write("\t".join([str(x) for x in entry]) + "\n")

    return bname
