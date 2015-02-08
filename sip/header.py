import datetime
import random
import re
import logging
import _util
import vb
from parse import Parser
import prot
import components
import field
import pdb

log = logging.getLogger(__name__)


class Header(Parser, vb.ValueBinder):
    """A SIP header."""

    types = _util.Enum(
        ("Accept", "Accept-Encoding", "Accept-Language", "Alert-Info", "Allow",
         "Authentication-Info", "Authorization", "Call-ID", "Call-Info",
         "Contact", "Content-Disposition", "Content-Encoding",
         "Content-Language", "Content-Length", "Content-Type", "CSeq", "Date",
         "Error-Info", "Expires", "From", "In-Reply-To", "Max-Forwards",
         "Min-Expires", "MIME-Version", "Organization", "Priority",
         "Proxy-Authenticate", "Proxy-Authorization", "Proxy-Require",
         "Record-Route", "Reply-To", "Require", "Retry-To", "Route", "Server",
         "Subject", "Supported", "Timestamp", "To", "Unsupported",
         "User-Agent", "Via", "Warning", "WWW-Authenticate"),
        normalize=_util.sipheader)

    # This allows us to generate instances of subclasses by class attribute
    # access, so Header.accept creates an accept header etc.
    __metaclass__ = _util.attributesubclassgen

    type = _util.ClassType("Header")
    value = _util.Value()

    parseinfo = {
        Parser.Pattern:
            "^\s*([^:\s]*)\s*:"  # The type.
            "\s*"
            "([^,]+)$"  # Everything else to be parsed in parsecust().
            "".format("|".join([
                _util.attributesubclassgen.NormalizeGeneratingAttributeName(
                    type)
                for type in types])),
        Parser.Constructor:
            (1, lambda type: getattr(Header, type)())
    }

    def parsecust(self, string, mo):

        data = mo.group(2)
        values = data.split(",")
        log.debug("Header values: %r", values)

        if not hasattr(self, "FieldDelegateClass"):
            try:
                self.values = values
            except AttributeError:
                log.debug(
                    "Can't set 'values' on instance of %r.", self.__class__)
            return

        fdc = self.FieldDelegateClass
        if hasattr(fdc, "Parse"):
            create = lambda x: fdc.Parse(x)
        else:
            create = lambda x: fdc(x)

        self.values = [create(val) for val in values]

    def __init__(self, values=None):
        """Initialize a header line.
        """
        super(Header, self).__init__()

        if values is None:
            values = list()

        self.__dict__["values"] = values

    def __str__(self):
        return "{0}: {1}".format(
            self.type, ",".join([str(v) for v in self.values]))


class FieldDelegateHeader(Header):
    """The FieldDelegateHeader delegates the work to a field class. Useful
    where the correct values are complex."""

    def __init__(self, *args, **kwargs):
        super(FieldDelegateHeader, self).__init__(*args, **kwargs)
        if not hasattr(self, "value"):
            self.value = self.FieldDelegateClass()

    def __setattr__(self, attr, val):
        if hasattr(self, "value"):
            myval = self.value
            if myval:
                dattrs = myval.delegateattributes
                if attr in dattrs:
                    setattr(myval, attr, val)
                    return

        super(FieldDelegateHeader, self).__setattr__(attr, val)
        return

    def __getattr__(self, attr):
        if attr != "value" and hasattr(self, "value"):
            myval = self.value
            dattrs = myval.delegateattributes
            if attr in dattrs:
                return getattr(myval, attr)
        try:
            return super(FieldDelegateHeader, self).__getattr__(attr)
        except AttributeError:
            raise AttributeError(
                "{self.__class__.__name__!r} object has no attribute "
                "{attr!r}".format(**locals()))


class ToHeader(FieldDelegateHeader):
    """A To: header"""
    FieldDelegateClass = field.PartyIDField


class FromHeader(FieldDelegateHeader):
    """A From: header"""
    FieldDelegateClass = field.PartyIDField


class ViaHeader(FieldDelegateHeader):
    """The Via: Header."""
    FieldDelegateClass = field.ViaField


class Call_IdHeader(Header):
    """Call ID header."""

    @classmethod
    def GenerateKey(cls):
        """Generate a random alphanumeric key.

        Returns a string composed of 6 random hexadecimal characters, followed
        by a hyphen, followed by a timestamp of form YYYYMMDDHHMMSS.
        """
        keyval = random.randint(0, 2**24 - 1)

        dt = datetime.datetime.now()
        keydate = (
            "{dt.year:04}{dt.month:02}{dt.day:02}{dt.hour:02}{dt.minute:02}"
            "{dt.second:02}".format(dt=dt))

        return "{keyval:06x}-{keydate}".format(**locals())

    def __init__(self, *args, **kwargs):
        Header.__init__(self, *args, **kwargs)
        self.host = None
        self.key = None

    @property
    def value(self):
        values = self.__dict__["values"]
        if values:
            return values[0]

        if self.key is None:
            self.key = Call_IdHeader.GenerateKey()

        if self.host:
            val = "{self.key}@{self.host}".format(self=self)
        else:
            val = "{self.key}".format(self=self)
        return val

    @property
    def values(self):
        values = self.__dict__["values"]
        if not values:
            values = [self.value]
            self.values = values
        return values

    @values.setter
    def values(self, values):
        self.__dict__["values"] = values


class CseqHeader(FieldDelegateHeader):
    FieldDelegateClass = field.CSeqField


class Max_ForwardsHeader(FieldDelegateHeader):
    FieldDelegateClass = field.Max_ForwardsField
