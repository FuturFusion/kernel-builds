#!/usr/bin/env python3

import os
import sys

FLAVOR = os.path.basename(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from genconfig import (
    finish,
    start,
)

kconf = start(defconfig="kernel/configs/kvm_guest.config")

finish()
