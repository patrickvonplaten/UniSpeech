# Copyright (c) 2017-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the license found in the LICENSE file in
# the root directory of this source tree. An additional grant of patent rights
# can be found in the PATENTS file in the same directory.

import logging
import os
import sys
from typing import Dict, List, Optional, Tuple

import numpy as np

from dataclasses import dataclass, field
from fairseq.data import Dictionary, UniSpeechSATDataset
from fairseq.dataclass.configs import FairseqDataclass
from fairseq.tasks import register_task
from fairseq.tasks.fairseq_task import FairseqTask
from omegaconf import MISSING

logger = logging.getLogger(__name__)


class LabelEncoder(object):
    def __init__(self, dictionary: Dictionary) -> None:
        self.dictionary = dictionary

    def __call__(self, label: str) -> List[str]:
        return self.dictionary.encode_line(
            label, append_eos=False, add_if_not_exist=False,
        )


@dataclass
class UniSpeechSATPretrainingConfig(FairseqDataclass):
    data: str = field(
        default=MISSING, metadata={"help": "path to data directory"}
    )
    fine_tuning: bool = field(
        default=False, metadata={"help": "set to true if fine-tuning Hubert"}
    )
    labels: List[str] = field(
        default_factory=lambda: ["ltr"],
        metadata={
            "help": (
                "extension of the label files to load, frame-level labels for"
                " pre-training, and sequence-level label for fine-tuning"
            )
        },
    )
    label_dir: Optional[str] = field(
        default=None,
        metadata={
            "help": "if set, looks for labels in this directory instead",
        },
    )
    label_rate: int = field(
        default=-1,
        metadata={"help": "label frame rate. -1 for sequence label"},
    )
    sample_rate: int = field(
        default=16_000,
        metadata={
            "help": "target sample rate. audio files will be up/down "
            "sampled to this rate"
        },
    )
    normalize: bool = field(
        default=False,
        metadata={
            "help": "if set, normalizes input to have 0 mean and unit variance"
        },
    )
    enable_padding: bool = field(
        default=False,
        metadata={"help": "pad shorter samples instead of cropping"},
    )
    max_sample_size: Optional[int] = field(
        default=None,
        metadata={"help": "max sample size to crop to for batching"},
    )
    min_sample_size: Optional[int] = field(
        default=None,
        metadata={"help": "min sample size to crop to for batching"},
    )
    single_target: Optional[bool] = field(
        default=False,
        metadata={
            "help": "if set, AddTargetDatasets outputs same keys "
            "as AddTargetDataset"
        },
    )
    random_crop: Optional[bool] = field(
        default=True,
        metadata={"help": "always crop from the beginning if false"},
    )
    pad_audio: Optional[bool] = field(
        default=False,
        metadata={"help": "pad audio to the longest one in the batch if true"},
    )

    # mixing utterance
    mixing_max_len: int = field(
        default=-1,
        metadata={"help": "the max length of utterance mixing. -1 denote half of the batch length."}
    )
    mixing_prob: float = field(
        default=0.5,
        metadata={"help": "the probability of utterance mixing"}
    )
    mixing_num: int = field(
        default=1,
        metadata={"help": "the num of utterances to mix for each sample"}
    )

    # mixing noise
    mixing_noise: bool = field(
        default=False,
        metadata={"help": "mixing noises"}
    )
    mixing_noise_prob: float = field(
        default=0.5,
        metadata={"help": "the probability of mixing noise"}
    )
    mixing_noise_num: int = field(
        default=1,
        metadata={"help": "the num of utterances to mix noise for each sample"}
    )
    noise_path: str = field(
        default="",
        metadata={"help": "the path of noises"}
    )


@register_task("unispeech_sat_pretraining", dataclass=UniSpeechSATPretrainingConfig)
class UniSpeechSATPretrainingTask(FairseqTask):

    cfg: UniSpeechSATPretrainingConfig

    def __init__(
        self,
        cfg: UniSpeechSATPretrainingConfig,
    ) -> None:
        super().__init__(cfg)

        logger.info(f"current directory is {os.getcwd()}")
        logger.info(f"HubertPretrainingTask Config {cfg}")

        self.cfg = cfg
        self.fine_tuning = cfg.fine_tuning

        if cfg.fine_tuning:
            self.state.add_factory("target_dictionary", self.load_dictionaries)
        else:
            self.state.add_factory("dictionaries", self.load_dictionaries)

        self._source_dictionary = None

        self.blank_symbol = "<s>"

    @property
    def source_dictionary(self) -> Optional[Dictionary]:
        return self._source_dictionary

    @property
    def target_dictionary(self) -> Optional[Dictionary]:
        return self.state.target_dictionary

    @property
    def dictionaries(self) -> List[Dictionary]:
        return self.state.dictionaries

    @classmethod
    def setup_task(
        cls, cfg: UniSpeechSATPretrainingConfig, **kwargs
    ) -> "UniSpeechSATPretrainingTask":
        return cls(cfg)

    def load_dictionaries(self):
        label_dir = self.cfg.data if self.cfg.label_dir is None else self.cfg.label_dir
        dictionaries = [Dictionary.load(f"{label_dir}/dict.{label}.txt") for label in self.cfg.labels]
        return dictionaries[0] if self.cfg.fine_tuning else dictionaries

    def get_label_dir(self) -> str:
        if self.cfg.label_dir is None:
            return self.cfg.data
        return self.cfg.label_dir

    def load_dataset(self, split: str, **kwargs) -> None:
        manifest = f"{self.cfg.data}/{split}.tsv"
        dicts = [self.target_dictionary] if self.cfg.fine_tuning else self.dictionaries
        pad_list = [dict.pad() for dict in dicts]
        eos_list = [dict.eos() for dict in dicts]
        procs = [LabelEncoder(dict) for dict in dicts]
        paths = [
            f"{self.get_label_dir()}/{split}.{l}" for l in self.cfg.labels
        ]

        self.datasets[split] = UniSpeechSATDataset(
            manifest,
            sample_rate=self.cfg.sample_rate,
            label_paths=paths,
            label_rates=self.cfg.label_rate,
            pad_list=pad_list,
            eos_list=eos_list,
            label_processors=procs,
            max_keep_sample_size=None,
            min_keep_sample_size=self.cfg.min_sample_size,
            max_sample_size=self.cfg.max_sample_size,
            pad_audio=self.cfg.pad_audio,
            normalize=self.cfg.normalize,
            store_labels=False,
            random_crop=self.cfg.random_crop,
            single_target=self.cfg.single_target,
            mixing_max_len=self.cfg.mixing_max_len,
            mixing_prob=self.cfg.mixing_prob,
            mixing_num=self.cfg.mixing_num,
            mixing_noise=self.cfg.mixing_noise,
            mixing_noise_prob=self.cfg.mixing_noise_prob,
            mixing_noise_num=self.cfg.mixing_noise_num,
            noise_path=self.cfg.noise_path,
        )

    def max_positions(self) -> Tuple[int, int]:
        return (sys.maxsize, sys.maxsize)

    def filter_indices_by_size(
        self, indices: np.array, *args, **kwargs
    ) -> np.array:
        return indices
