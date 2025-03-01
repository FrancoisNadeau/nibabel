"""
Descriptor support for NIPY.

Utilities to support special Python descriptors [1,2], in particular the use of
a useful pattern for properties we call 'one time properties'.  These are
object attributes which are declared as properties, but become regular
attributes once they've been read the first time.  They can thus be evaluated
later in the object's life cycle, but once evaluated they become normal, static
attributes with no function call overhead on access or any other constraints.

A special ResetMixin class is provided to add a .reset() method to users who
may want to have their objects capable of resetting these computed properties
to their 'untriggered' state.

References
----------
[1] How-To Guide for Descriptors, Raymond
Hettinger. https://docs.python.org/howto/descriptor.html

[2] Python data model, https://docs.python.org/reference/datamodel.html
"""

from nibabel.deprecated import deprecate_with_version

# -----------------------------------------------------------------------------
# Classes and Functions
# -----------------------------------------------------------------------------


class ResetMixin:
    """A Mixin class to add a .reset() method to users of OneTimeProperty.

    By default, auto attributes once computed, become static.  If they happen
    to depend on other parts of an object and those parts change, their values
    may now be invalid.

    This class offers a .reset() method that users can call *explicitly* when
    they know the state of their objects may have changed and they want to
    ensure that *all* their special attributes should be invalidated.  Once
    reset() is called, all their auto attributes are reset to their
    OneTimeProperty descriptors, and their accessor functions will be triggered
    again.

    .. warning::

       If a class has a set of attributes that are OneTimeProperty, but that
       can be initialized from any one of them, do NOT use this mixin!  For
       instance, UniformTimeSeries can be initialized with only sampling_rate
       and t0, sampling_interval and time are auto-computed.  But if you were
       to reset() a UniformTimeSeries, it would lose all 4, and there would be
       then no way to break the circular dependency chains.

       If this becomes a problem in practice (for our analyzer objects it
       isn't, as they don't have the above pattern), we can extend reset() to
       check for a _no_reset set of names in the instance which are meant to be
       kept protected.  But for now this is NOT done, so caveat emptor.

    Examples
    --------

    >>> class A(ResetMixin):
    ...     def __init__(self,x=1.0):
    ...         self.x = x
    ...
    ...     @auto_attr
    ...     def y(self):
    ...         print('*** y computation executed ***')
    ...         return self.x / 2.0
    ...

    >>> a = A(10)

    About to access y twice, the second time no computation is done:
    >>> a.y
    *** y computation executed ***
    5.0
    >>> a.y
    5.0

    Changing x
    >>> a.x = 20

    a.y doesn't change to 10, since it is a static attribute:
    >>> a.y
    5.0

    We now reset a, and this will then force all auto attributes to recompute
    the next time we access them:
    >>> a.reset()

    About to access y twice again after reset():
    >>> a.y
    *** y computation executed ***
    10.0
    >>> a.y
    10.0
    """

    def reset(self):
        """Reset all OneTimeProperty attributes that may have fired already."""
        instdict = self.__dict__
        classdict = self.__class__.__dict__
        # To reset them, we simply remove them from the instance dict.  At that
        # point, it's as if they had never been computed.  On the next access,
        # the accessor function from the parent class will be called, simply
        # because that's how the python descriptor protocol works.
        for mname, mval in classdict.items():
            if mname in instdict and isinstance(mval, OneTimeProperty):
                delattr(self, mname)


class OneTimeProperty:
    """A descriptor to make special properties that become normal attributes.

    This is meant to be used mostly by the auto_attr decorator in this module.
    """

    def __init__(self, func):
        """Create a OneTimeProperty instance.

        Parameters
        ----------
          func : method

          The method that will be called the first time to compute a value.
          Afterwards, the method's name will be a standard attribute holding
          the value of this computation.
        """
        self.getter = func
        self.name = func.__name__

    def __get__(self, obj, type=None):
        """This will be called on attribute access on the class or instance."""
        if obj is None:
            # Being called on the class, return the original function. This
            # way, introspection works on the class.
            # return func
            return self.getter

        # Errors in the following line are errors in setting a
        # OneTimeProperty
        val = self.getter(obj)

        setattr(obj, self.name, val)
        return val


def auto_attr(func):
    """Decorator to create OneTimeProperty attributes.

    Parameters
    ----------
      func : method
        The method that will be called the first time to compute a value.
        Afterwards, the method's name will be a standard attribute holding the
        value of this computation.

    Examples
    --------
    >>> class MagicProp:
    ...     @auto_attr
    ...     def a(self):
    ...         return 99
    ...
    >>> x = MagicProp()
    >>> 'a' in x.__dict__
    False
    >>> x.a
    99
    >>> 'a' in x.__dict__
    True
    """
    return OneTimeProperty(func)


# -----------------------------------------------------------------------------
# Deprecated API
# -----------------------------------------------------------------------------

# For backwards compatibility
setattr_on_read = deprecate_with_version(
    message="setattr_on_read has been renamed to auto_attr. Please use nibabel.onetime.auto_attr",
    since="3.2", until="5.0")(auto_attr)
