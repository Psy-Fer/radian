import cProfile
import os
from pathlib import Path

import numpy as np

from beam_search_decoder import ctcBeamSearch

def main():
    # cProfile.run("callback()", sort="cumtime")

    # Data directory

    data_dir = "/mnt/sda/rna-basecaller/experiments/global-decoding/train-3-37/val_test/8_TestGlobalDecoding/1_CombineSoftmaxes/hek293"

    # Load read IDs

    id_file = "/mnt/sda/rna-basecaller/experiments/global-decoding/train-3-37/val_test/5_WriteToNumpy/hek293/hek293_read_ids.npy"
    with open(id_file, "rb") as f:
        read_ids = np.load(f, allow_pickle=True)
    print(len(read_ids))

    # Combine all reads together so we can iterate more easily

    npy_paths = sorted(Path(data_dir).iterdir(), key=os.path.getmtime)
    with open(npy_paths[0], "rb") as f:
        read_global_softmaxes = np.load(f, allow_pickle=True)
    for path in npy_paths[1:]:
        with open(path, "rb") as f:
            read_global_softmaxes = np.concatenate((read_global_softmaxes, np.load(f, allow_pickle=True)))
    print(len(read_global_softmaxes))

    classes = 'ACGT'
    rna_model = None
    global_preds = []
    for softmax in read_global_softmaxes:
        pred = ctcBeamSearch(softmax, classes, rna_model, None)
        global_preds.append(pred)
    with open(f"{data_dir}/global_preds_hek293.npy", "wb") as f:
        np.save(f, global_preds)

# def callback():
#     npy_file = "/mnt/sda/rna-basecaller/experiments/global-decoding/train-3-37/val_test/8_TestGlobalDecoding/1_CombineSoftmaxes/hek293/hek293_read_global_softmaxes_100.npy"

#     with open(npy_file, "rb") as f:
#         read_global_softmaxes = np.load(f, allow_pickle=True)

#     classes = 'ACGT'
#     ctcBeamSearch(read_global_softmaxes[0], classes, None, None)

if __name__ == "__main__":
    main()