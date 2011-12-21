""" Array writer objects

Array writers have init signature::

    def __init__(self, array, out_dtype=None)

and methods

* to_fileobj(fileobj, offset=None, order='F')

They do have attributes:

* array
* out_dtype

They are designed to write arrays to a fileobj with reasonable memory
efficiency.

Array writers may be able to scale the array or apply an intercept, or do
something else to make sense of conversions between float and int, or between
larger ints and smaller.
"""

import numpy as np

from .casting import shared_range, int_to_float, as_int
from .volumeutils import finite_range, array_to_file


class WriterError(Exception):
    pass


class ScalingError(WriterError):
    pass


class ArrayWriter(object):

    def __init__(self, array, out_dtype=None, calc_scale=True):
        """ Initialize array writer

        Parameters
        ----------
        array : array-like
            array-like object
        out_dtype : None or dtype
            dtype with which `array` will be written.  For this class,
            `out_dtype`` needs to be the same as the dtype of the input `array`
            or a swapped version of the same.
        \*\*kwargs : keyword arguments

        Examples
        --------
        >>> arr = np.array([0, 255], np.uint8)
        >>> aw = ArrayWriter(arr)
        >>> aw = ArrayWriter(arr, np.int8)
        Traceback (most recent call last):
            ...
        WriterError: Scaling needed but cannot scale
        """
        self._array = np.asanyarray(array)
        arr_dtype = self._array.dtype
        if out_dtype is None:
            out_dtype = arr_dtype
        else:
            out_dtype = np.dtype(out_dtype)
        self._out_dtype = out_dtype
        if self.scaling_needed():
            raise WriterError("Scaling needed but cannot scale")

    def scaling_needed(self):
        """ Checks if scaling is needed for input array

        Raises WriterError if no scaling possible.

        The rules are in the code, but:
        * If numpy will cast, return False (no scaling needed)
        * If input or output is an object or structured type, raise
        * If input is complex, raise
        * If the output is float, return False
        * If there is no finite value in the input array, or the input array is
          all 0, return False (the writer will strip the non-finite values)
        * By now we are casting to (u)int. If the input type is a float, return
          True (we do need scaling)
        * Now input and output types are (u)ints. If the min and max in the data
          are within range of the output type, return False
        * Otherwise return True
        """
        data = self._array
        arr_dtype = data.dtype
        out_dtype = self._out_dtype
        if np.can_cast(arr_dtype, out_dtype):
            return False
        if 'V' in (arr_dtype.kind, out_dtype.kind):
            raise WriterError('Cannot cast to or from non-numeric types')
        if out_dtype.kind == 'c':
            return False
        if arr_dtype.kind == 'c':
            raise WriterError('Cannot cast complex types to non-complex')
        if out_dtype.kind == 'f':
            return False
        # Now we need to look at the data for special cases
        mn, mx = self.finite_range() # this is cached
        if (mn, mx) in ((0, 0), (np.inf, -np.inf)):
            # Data all zero, or no data is finite
            return False
        if arr_dtype.kind == 'f':
            return True
        assert arr_dtype.kind in 'iu' and out_dtype.kind in 'iu'
        info = np.iinfo(out_dtype)
        if mn >= info.min and mx <= info.max:
                return False
        return True

    @property
    def array(self):
        """ Return array from arraywriter """
        return self._array

    @property
    def out_dtype(self):
        """ Return `out_dtype` from arraywriter """
        return self._out_dtype

    def finite_range(self):
        """ Return (maybe cached) finite range of data array """
        try:
            return self._finite_range
        except AttributeError:
            pass
        self._finite_range = finite_range(self._array)
        return self._finite_range

    def _writing_range(self):
        """ Finite range for thresholding on write """
        if self._out_dtype.kind in 'iu' and self._array.dtype.kind == 'f':
            mn, mx = self.finite_range()
            if (mn, mx) == (np.inf, -np.inf): # no finite data
                mn, mx = 0, 0
            return mn, mx
        return None, None

    def to_fileobj(self, fileobj, order='F', nan2zero=True):
        """ Write array into `fileobj`

        Parameters
        ----------
        fileobj : file-like object
        order : {'F', 'C'}
            order (Fortran or C) to which to write array
        nan2zero : {True, False}, optional
            Whether to set NaN values to 0 when writing integer output.
            Defaults to True.  If False, NaNs get converted with numpy
            ``astype``, and the behavior is undefined.  Ignored for floating
            point output.
        """
        mn, mx = self._writing_range()
        array_to_file(self._array,
                      fileobj,
                      self._out_dtype,
                      offset=None,
                      mn=mn,
                      mx=mx,
                      order=order,
                      nan2zero=nan2zero)


class SlopeArrayWriter(ArrayWriter):

    def __init__(self, array, out_dtype=None, calc_scale=True,
                 scaler_dtype=np.float32):
        """ Initialize array writer

        Parameters
        ----------
        array : array-like
            array-like object
        out_dtype : None or dtype
            dtype with which `array` will be written.  For this class,
            `out_dtype`` needs to be the same as the dtype of the input `array`
            or a swapped version of the same.
        calc_scale : {True, False}, optional
            Whether to calculate scaling for writing `array` on initialization.
            If False, then you can calculate this scaling with
            ``obj.calc_scale()`` - see examples
        scaler_dtype : dtype-like, optional
            specifier for numpy dtype for scaling

        Examples
        --------
        >>> arr = np.array([0, 254], np.uint8)
        >>> aw = SlopeArrayWriter(arr)
        >>> aw.slope
        1.0
        >>> aw = SlopeArrayWriter(arr, np.int8)
        >>> aw.slope
        2.0
        >>> aw = SlopeArrayWriter(arr, np.int8, calc_scale=False)
        >>> aw.slope
        1.0
        >>> aw.calc_scale()
        >>> aw.slope
        2.0
        """
        self._array = np.asanyarray(array)
        arr_dtype = self._array.dtype
        if out_dtype is None:
            out_dtype = arr_dtype
        else:
            out_dtype = np.dtype(out_dtype)
        self._out_dtype = out_dtype
        self.needs_scale = self.scaling_needed()
        self.scaler_dtype = np.dtype(scaler_dtype)
        self.slope = 1.0
        self._scale_calced = False
        if calc_scale:
            self.calc_scale()

    def _get_slope(self):
        return self._slope
    def _set_slope(self, val):
        self._slope = np.squeeze(self.scaler_dtype.type(val))
    slope = property(_get_slope, _set_slope, None, 'get/set slope')

    def calc_scale(self, force=False):
        """ Calculate / set scaling for floats/(u)ints to (u)ints
        """
        # If we've run already, return unless told otherwise
        if not force and self._scale_calced:
            return
        self._scale_calced = True
        if not self.scaling_needed():
            return
        self._do_scaling()

    def to_fileobj(self, fileobj, order='F', nan2zero=True):
        """ Write array into `fileobj`

        Parameters
        ----------
        fileobj : file-like object
        order : {'F', 'C'}
            order (Fortran or C) to which to write array
        nan2zero : {True, False}, optional
            Whether to set NaN values to 0 when writing integer output.
            Defaults to True.  If False, NaNs get converted with numpy
            ``astype``, and the behavior is undefined.  Ignored for floating
            point output.
        """
        mn, mx = self._writing_range()
        array_to_file(self._array,
                      fileobj,
                      self._out_dtype,
                      offset=None,
                      divslope=self.slope,
                      mn=mn,
                      mx=mx,
                      order=order,
                      nan2zero=nan2zero)

    def _do_scaling(self):
        arr = self._array
        arr_dtype = arr.dtype
        out_dtype = self._out_dtype
        assert out_dtype.kind in 'iu'
        mn, mx = self.finite_range()
        if arr_dtype.kind == 'f':
            # Float to (u)int scaling
            self._range_scale()
            return
        # (u)int to (u)int
        info = np.iinfo(out_dtype)
        out_max, out_min = info.max, info.min
        if mx <= out_max and mn >= out_min: # already in range
            return
        # (u)int to (u)int scaling
        if self._out_dtype.kind == 'u':
            shared_min, shared_max = shared_range(self.scaler_dtype,
                                                  self._out_dtype)
            if mx <= 0 and abs(mn) <= shared_max: # sign flip enough?
                # -1.0 * arr will be in scaler_dtype precision
                self.slope = -1.0
                return
        self._range_scale()

    def _range_scale(self):
        """ Calculate scaling based on data range and output type """
        mn, mx = self.finite_range() # These can be floats or integers
        # We need to allow for precision of the type to which we will scale
        # These will be floats of type scaler_dtype
        shared_min, shared_max = shared_range(self.scaler_dtype,
                                              self._out_dtype)
        # But we want maximum precision for the calculations
        shared_min, shared_max = np.array([shared_min, shared_max],
                                          dtype = np.longdouble)
        if self._out_dtype.kind == 'u':
            if mn < 0 and mx > 0:
                raise WriterError('Cannot scale negative and positive '
                                  'numbers to uint without intercept')
            if mx <= 0: # All input numbers <= 0
                self.slope = mn / shared_max
            else: # All input numbers > 0
                self.slope = mx / shared_max
            return
        # Scaling to int. We need the bigger slope of (mn/shared_min) and
        # (mx/shared_max). If the mn or the max is the wrong side of 0, that
        # will make these negative and so they won't worry us
        mx_slope = mx / shared_max
        mn_slope = mn / shared_min
        self.slope = np.max([mx_slope, mn_slope])


class SlopeInterArrayWriter(SlopeArrayWriter):

    def __init__(self, array, out_dtype=None, calc_scale=True,
                 scaler_dtype=np.float32):
        """ Initialize array writer

        Parameters
        ----------
        array : array-like
            array-like object
        out_dtype : None or dtype
            dtype with which `array` will be written.  For this class,
            `out_dtype`` needs to be the same as the dtype of the input `array`
            or a swapped version of the same.
        calc_scale : {True, False}, optional
            Whether to calculate scaling for writing `array` on initialization.
            If False, then you can calculate this scaling with
            ``obj.calc_scale()`` - see examples
        scaler_dtype : dtype-like, optional
            specifier for numpy dtype for scaling

        Examples
        --------
        >>> arr = np.array([0, 255], np.uint8)
        >>> aw = SlopeInterArrayWriter(arr)
        >>> aw.slope, aw.inter
        (1.0, 0.0)
        >>> aw = SlopeInterArrayWriter(arr, np.int8)
        >>> (aw.slope, aw.inter) == (1.0, 128)
        True
        >>> aw = SlopeInterArrayWriter(arr, np.int8, calc_scale=False)
        >>> aw.slope, aw.inter
        (1.0, 0.0)
        >>> aw.calc_scale()
        >>> (aw.slope, aw.inter) == (1.0, 128)
        True
        """
        super(SlopeInterArrayWriter, self).__init__(array, out_dtype, False,
                                                    scaler_dtype)
        self.inter = 0.0
        if calc_scale:
            self.calc_scale()

    def _get_inter(self):
        return self._inter
    def _set_inter(self, val):
        self._inter = np.squeeze(self.scaler_dtype.type(val))
    inter = property(_get_inter, _set_inter, None, 'get/set inter')

    def to_fileobj(self, fileobj, order='F', nan2zero=True):
        """ Write array into `fileobj`

        Parameters
        ----------
        fileobj : file-like object
        order : {'F', 'C'}
            order (Fortran or C) to which to write array
        nan2zero : {True, False}, optional
            Whether to set NaN values to 0 when writing integer output.
            Defaults to True.  If False, NaNs get converted with numpy
            ``astype``, and the behavior is undefined.  Ignored for floating
            point output.
        """
        mn, mx = self._writing_range()
        array_to_file(self._array,
                      fileobj,
                      self._out_dtype,
                      offset=None,
                      intercept=self.inter,
                      divslope=self.slope,
                      mn=mn,
                      mx=mx,
                      order=order,
                      nan2zero=nan2zero)

    def _do_scaling(self):
        """ Calculate / set scaling for floats/(u)ints to (u)ints
        """
        arr = self._array
        arr_dtype = arr.dtype
        out_dtype = self._out_dtype
        assert out_dtype.kind in 'iu'
        mn, mx = self.finite_range()
        if mn == np.inf : # No valid data
            return
        if (mn, mx) == (0.0, 0.0): # Data all zero
            return
        if arr_dtype.kind == 'f':
            # Float to (u)int scaling
            self._range_scale()
            return
        # (u)int to (u)int
        info = np.iinfo(out_dtype)
        out_max, out_min = info.max, info.min
        if mx <= out_max and mn >= out_min: # already in range
            return
        # (u)int to (u)int scaling
        if self._out_dtype.kind == 'u':
            shared_min, shared_max = shared_range(self.scaler_dtype,
                                                  self._out_dtype)
            # range may be greater than the largest integer for this type.
            # as_int needed to work round numpy 1.4.1 int casting bug
            mn2mx = as_int(mx) - as_int(mn)
            if mn2mx <= shared_max: # offset enough?
                self.inter = mn
                return
            if mx <= 0 and abs(mn) <= shared_max: # sign flip enough?
                # -1.0 * arr will be in scaler_dtype precision
                self.slope = -1.0
                return
        self._range_scale()

    def _range_scale(self):
        """ Calculate scaling, intercept based on data range and output type """
        mn, mx = self.finite_range() # Values of self.array.dtype type
        if mx == mn: # Only one number in array
            self.inter = mn
            return
        # We need to allow for precision of the type to which we will scale
        # These will be floats of type scaler_dtype
        shared_min, shared_max = shared_range(self.scaler_dtype,
                                              self._out_dtype)
        scaled_mn2mx = np.diff(np.array([shared_min, shared_max],
                                        dtype=np.longdouble))
        # Straight mx-mn can overflow.
        if mn.dtype.kind == 'f': # Already floats
            # float64 and below cast correctly to longdouble.  Longdouble needs
            # no casting
            mn2mx = np.diff(np.array([mn, mx], dtype=np.longdouble))
        else: # max possible (u)int range is 2**64-1 (int64, uint64)
            # int_to_float covers this range.  On windows longdouble is the same
            # as double so mn2mx will be 2**64 - thus overestimating slope
            # slightly.  Casting to int needed to allow mx-mn to be larger than
            # the largest (u)int value
            mn2mx = int_to_float(as_int(mx) - as_int(mn), np.longdouble)
        slope = mn2mx / scaled_mn2mx
        self.inter = mn - shared_min * slope
        self.slope = slope
        if not np.all(np.isfinite([self.slope, self.inter])):
            raise ScalingError("Slope / inter not both finite")


def get_slope_inter(writer):
    """ Return slope, intercept from array writer object

    Parameters
    ----------
    writer : ArrayWriter instance

    Returns
    -------
    slope : scalar
        slope in `writer` or 1.0 if not present
    inter : scalar
        intercept in `writer` or 0.0 if not present
    """
    try:
        slope = writer.slope
    except AttributeError:
        slope = 1.0
    try:
        inter = writer.inter
    except AttributeError:
        inter = 0.0
    return slope, inter


def make_array_writer(data, out_type, has_intercept=True, has_slope=True,
                      **kwargs):
    """ Make array writer instance for array `data` and output type `out_type`

    Parameters
    ----------
    data : array-like
        array for which to create array writer
    out_type : dtype-like
        input to numpy dtype to specify array writer output type
    has_intercept : {True, False}
        If True, array write can use intercept to adapt the array to `out_type`
    has_slope : {True, False}
        If True, array write can use scaling to adapt the array to `out_type`
    \*\*kwargs : other keyword arguments
        to pass to the arraywriter class, if it accepts them.

    Returns
    -------
    writer : arraywriter instance
        Instance of array writer, with class adapted to `has_intercept` and
        `has_slope`.
    """
    data = np.asarray(data)
    if has_intercept == True and has_slope == False:
        raise ValueError('Cannot handle intercept without slope')
    if has_intercept:
        return SlopeInterArrayWriter(data, out_type, **kwargs)
    if has_slope:
        return SlopeArrayWriter(data, out_type, **kwargs)
    return ArrayWriter(data, out_type)
