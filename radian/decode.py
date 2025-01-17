"""
This has been adapted from https://github.com/githubharald/CTCDecoder/blob/master/ctc_decoder/beam_search.py
"""

from collections import defaultdict
from dataclasses import dataclass
import math
from typing import List, Tuple

import numpy as np
import tensorflow as tf


N_BASES = 4

def log(x: float) -> float:
    return -math.inf if x == 0 else math.log(x)


@dataclass
class BeamEntry:
    """Information about one single beam at specific time-step."""
    pr_total: float = log(0)  # blank and non-blank
    pr_non_blank: float = log(0)  # non-blank
    pr_blank: float = log(0)  # blank
    labeling: tuple = ()  # beam-labeling


class BeamList:
    """Information about all beams at specific time-step."""

    def __init__(self) -> None:
        self.entries = defaultdict(BeamEntry)

    def sort_labelings(self) -> List[Tuple[int]]:
        """Return beam-labelings, sorted by probability."""
        beams = self.entries.values()
        sorted_beams = sorted(beams, reverse=True, key=lambda x: x.pr_total)
        return [x.labeling for x in sorted_beams]


def get_context(labeling, len_context, exclude_last=False):
    # the context is the last portion of the beam
    if exclude_last == True:
        context = labeling[-(len_context+1):-1]
    else:
        context = labeling[-len_context:]

    return context


def combine_dists(r_dist, s_dist):
    # get the base (i.e. non-blank) distribution from the signal model
    s_base_prob = np.sum(s_dist[:-1])
    s_base_dist = s_dist[:-1] / s_base_prob

    # average the signal and rna model probs
    c_dist = np.add(r_dist, s_base_dist) / 2

    # reconstruct the signal model distribution (including blank)
    c_dist = c_dist * s_base_prob
    c_dist = np.append(c_dist, s_dist[-1])

    return c_dist


def normalise(dist):
    if sum(dist) == 0:
        return dist
    return dist / sum(dist)


def entropy(dist):
    # Events with probability 0 do not contribute to the entropy
    dist = dist[dist > 0]
    return -sum([p * math.log(p) for p in dist])


def apply_rna_model(s_dist, context, model, entr_cache, s_entropy, r_threshold, s_threshold):
    if model is None:
        return s_dist

    r_dist = np.asarray(model[context])

    # compute the entropy of the RNA model distribution (speed up with cache)
    if context not in entr_cache:
        r_entropy = entropy(r_dist)
        entr_cache[context] = r_entropy
    else:
        r_entropy = entr_cache[context]

    # combine the probability distributions from the RNA and sig2seq models
    if r_entropy < r_threshold and s_entropy > s_threshold:
        return combine_dists(r_dist, s_dist)
    else:
        return s_dist


# TODO: Define class for decoding params
def beam_search(
    mat: np.ndarray,
    bases: str,
    beam_width: int,
    lm: tf.keras.Model,
    s_threshold: int,
    r_threshold: int,
    len_context: int,
    entr_cache: dict
) -> str:
    """Beam search decoder.

    See the paper of Hwang et al. and the paper of Graves et al.

    Args:
        mat: Output of neural network of shape TxC.
        bases: The set of bases the neural network can recognize, excluding the CTC-blank.
        beam_width: Number of beams kept per iteration.
        lm: Character level language model if specified.

    Returns:
        The decoded text.
    """

    blank_idx = len(bases)
    timesteps, chars = mat.shape

    # initialise beam state
    last = BeamList()
    labeling = ()
    last.entries[labeling] = BeamEntry()
    last.entries[labeling].pr_blank = log(1)
    last.entries[labeling].pr_total = log(1)

    # pre-compute entropy for each timestep in the softmax matrix
    s_entropies = []
    for t in range(timesteps):
        # don't include the blank symbol, so we need to first normalise
        s_entropies.append(entropy(normalise(mat[t][:-1])))

    # go over all time-steps
    for t in range(timesteps):
        curr = BeamList()

        # get beam-labelings of best beams
        best_labelings = last.sort_labelings()[:beam_width]

        # go over best beams
        for labeling in best_labelings:

            # COPY BEAM

            # probability of paths ending with a non-blank
            pr_non_blank = log(0)
            # in case of non-empty beam
            if labeling:
                # apply RNA model to the posteriors
                if lm and len(labeling) >= len_context + 1:
                    # TODO: Add comment on why we exclude last
                    context = get_context(labeling, len_context, exclude_last=True)
                    # TODO: Reconsider if RNA model should be applied here
                    pr_dist = apply_rna_model(mat[t], context, lm, entr_cache, s_entropies[t], r_threshold, s_threshold)
                else:
                    pr_dist = mat[t]

                pr_non_blank = last.entries[labeling].pr_non_blank + log(pr_dist[labeling[-1]])

            # probability of paths ending with a blank
            pr_blank = last.entries[labeling].pr_total + log(mat[t, blank_idx])

            # fill in data for current beam
            curr.entries[labeling].labeling = labeling
            curr.entries[labeling].pr_non_blank = np.logaddexp(curr.entries[labeling].pr_non_blank, pr_non_blank)
            curr.entries[labeling].pr_blank = np.logaddexp(curr.entries[labeling].pr_blank, pr_blank)
            curr.entries[labeling].pr_total = np.logaddexp(curr.entries[labeling].pr_total,
                                                           np.logaddexp(pr_blank, pr_non_blank))

            # EXTEND BEAM

            # apply RNA model to the posteriors
            if lm and len(labeling) >= len_context:
                context = get_context(labeling, len_context, exclude_last=False)
                pr_dist = apply_rna_model(mat[t], context, lm, entr_cache, s_entropies[t], r_threshold, s_threshold)
            else:
                pr_dist = mat[t]

            # extend current beam-labeling
            for c in range(chars - 1):
                # add new char to current beam-labeling
                new_labeling = labeling + (c,)

                # if new labeling contains duplicate char at the end, only consider paths ending with a blank
                if labeling and labeling[-1] == c:
                    pr_non_blank = last.entries[labeling].pr_blank + log(pr_dist[c])
                else:
                    pr_non_blank = last.entries[labeling].pr_total + log(pr_dist[c])

                # fill in data TODO: Refactor
                curr.entries[new_labeling].labeling = new_labeling
                curr.entries[new_labeling].pr_non_blank = np.logaddexp(curr.entries[new_labeling].pr_non_blank,
                                                                       pr_non_blank)
                curr.entries[new_labeling].pr_total = np.logaddexp(curr.entries[new_labeling].pr_total, pr_non_blank)

        # set new beam state
        last = curr

    # sort by probability
    best_labeling = last.sort_labelings()[0]

    # map label string to sequence of bases
    best_seq = ''.join([bases[label] for label in best_labeling])

    return best_seq