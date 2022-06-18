# emacs: -*- mode: python-mode; py-indent-offset: 4; indent-tabs-mode: nil -*-
# vi: set ft=python sts=4 ts=4 sw=4 et:
### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
#
#   See COPYING file distributed along with the NiBabel package for the
#   copyright and license terms.
#
### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##

from ..gifti import GiftiImage
from ..giftiio import read, write
from .test_parse_gifti_fast import DATA_FILE1
from ...deprecator import ExpiredDeprecationError

import pytest


def test_read_deprecated(tmp_path):
    with pytest.raises(ExpiredDeprecationError):
        read(DATA_FILE1)

    img = GiftiImage.from_filename(DATA_FILE1)
    fname = tmp_path / 'test.gii'
    with pytest.raises(ExpiredDeprecationError):
        write(img, fname)
