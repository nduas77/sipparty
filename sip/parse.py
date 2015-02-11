"""parse.py

Parsing mixin class for unpacking objects from regular expression based
pattern matching.

Copyright 2015 David Park

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
import re
import logging
import pdb

log = logging.getLogger(__name__)
log.level = logging.DEBUG


class ParseError(Exception):
    pass


class Parser(object):
    """This mixin class provides a way of parsing hierarchical text into an
    object graph using regular expressions.

    A parse is triggered by a subclass of Parser calling the class method
    Parse. The result of this will either be a ParseError raised because the
    parse failed, or an instance of the subclass.

    ## Basic example.

    The simplest example is a class that creates an instance of itself and
    configures some attributes based on the values in the data.

    For example:

        class KeyValue(Parser):
            parseinfo = {
                Parser.Pattern:
                    "(.+):(.+)",
                Parser.Mappings:
                    [("key",),
                     ("value",)]
            }

        kv = KeyValue.Parse("a:b")
        kv.key
        > "a"
        kv.value
        > "b"

    ### Attribute customization

    To get more complicated object graphs, constructors for the attributes may
    be used. For example:

    class KeyValue(Parser):
        ...
            Parser.Mappings:
                [("key", Key),
                 ("value", Value)]
        ...

    kv = KeyValue.Parse("a:b")
    kv.key
    > Key("a")
    kv.value
    > Value("b")

    The index into the mapping corresponds to the group from the regular
    expression, starting at one. So in the above case, the first "(.+)" from
    the pattern is passed to Key.Parse(), and the second "(.+)" is passed to
    Value.Parse().

    If 'Key' had had a Parse method, then that would have been called to
    generate the instance. Otherwise 'Key' itself would have been called.

    ### Pre-attribute data transformation

    Further, a third entry may be added to the mapping tuple to transform the
    data before passing it to the constructor. For example:

    class KeyValue(Parser):
        ...
            Parser.Mappings:
                [("key", Key, lambda x: x.lower()),
        ...

    Here we are specifying that the key should be made lower case before the
    constructor is called.

    ## Constructor customization

    Instead of looking for a Parse method in the class, or calling the class
    itself to construct the instance, a constructor (a callable) can be
    specified in the parseinfo dictionary:

        ...
            Parser.Constructor:
                (1, lambda a: ConstructObject(a))
        ...

    Here the first item in the tuple indicates the text group from the pattern
    that should be passed to the constructor as the single argument.

    Once the object is constructed, any further attributes from the mapping
    list will be set on that object.

    ## Repetition.

    """
    # These are keys that can be used in the parseinfo
    Pattern = "pattern"
    RE = "re"  # This will be compiled from the pattern automatically.
    Mappings = "mappings"
    # Class = "class"
    # Data = "data"
    Constructor = "constructor"
    Repeats = "repeat"

    @classmethod
    def ParseFail(cls, string, *args, **kwargs):
        log.warning("Parse failure of message %r", string)
        for key, val in kwargs.iteritems():
            log.debug("%r=%r", key, val)
        raise ParseError(
            "{cls.__name__!r} type failed to parse text {string!r}. Extra "
            "info: {args}"
            "".format(**locals()))

    @classmethod
    def SimpleParse(cls, string):
        if not hasattr(cls, "parseinfo"):
            raise TypeError(
                "{cls.__name__!r} does not support parsing (has no "
                "'parseinfo' field)."
                "".format(**locals()))

        log.debug("SimpleParse with parseinfo %r", cls.parseinfo)

        pi = cls.parseinfo
        if Parser.RE not in pi:
            # not compiled yet.
            try:
                ptrn = pi[Parser.Pattern]
            except KeyError:
                raise TypeError(
                    "{0!r} does not have a Parser.Pattern in its "
                    "'parseinfo' dictionary.".format(cls))
            log.debug("Compile re %s", ptrn)
            pi[Parser.RE] = re.compile(ptrn)

        pre = pi[Parser.RE]
        mo = pre.match(string)
        if mo is None:
            cls.ParseFail(string, "Pattern was %r" % pi[Parser.Pattern])

        return mo

    @classmethod
    def Parse(cls, string):
        """The aim of this class method is to produce a fully initialized
        instance of this class (or in fact any class inheriting from Parser)
        from some text. If it fails to parse the text it should raise a
        ParseError.
        """
        pi = cls.parseinfo

        if Parser.Repeats in pi and pi[Parser.Repeats]:
            log.debug("Repeating parser for class %s", cls.__name__)
            result = []
            repeats = True
        else:
            log.debug("Non-repeating parser for class %s", cls.__name__)
            repeats = False

        while len(string) > 0:
            log.debug("Parse remaining data %r", string)
            mo = cls.SimpleParse(string)

            if Parser.Constructor in pi:
                constructor_tuple = pi[Parser.Constructor]
                log.debug("Using constructor %r", constructor_tuple)
                constructor_gp = constructor_tuple[0]
                constructor_func = constructor_tuple[1]
                constructor_data = mo.group(constructor_gp)
                obj = constructor_func(constructor_data)
                if obj is None:
                    cls.ParseFail(
                        string,
                        "Could not construct the object from the data.")
            else:
                log.debug("No constructor: new version of class %r",
                          cls.__name__)
                obj = cls()

            log.debug("Parse %r", obj)
            obj.parse(string, mo)

            if not repeats:
                log.debug("Not a repeater; finished.")
                result = obj
                break

            result.append(obj)
            assert mo is not None, (
                "A repeating parser failed a match that didn't cause an "
                "exception.")
            string = string[len(mo.group(0)):]

        log.debug("Parse result %r", result)
        return result

    def parse(self, string, mo=None):
        log.debug("%r parse %s", self, string)

        if mo is None:
            mo = self.SimpleParse(string)

        if Parser.Mappings in self.parseinfo:
            mappings = self.parseinfo[Parser.Mappings]
            self.parsemappings(mo, mappings)

        # Finally do parsecust, if specified.
        if hasattr(self, "parsecust"):
            self.parsecust(string=string, mo=mo)

    def parsemappings(self, mo, mappings):
        log.debug("Apply mappings %r", mappings)
        for mapping, gpnum in zip(mappings, range(1, len(mappings) + 1)):
            if mapping is None:
                continue

            data = mo.group(gpnum)
            if not data:
                # No data in this group so nothing to parse. If a group can
                # have no data then that implies this mapping is optional.
                log.debug("No data for mapping %r", mapping)
                continue

            log.debug("Apply mapping %r to group %d", mapping, gpnum)
            attr = mapping[0]
            cls = str
            gen = lambda x: x
            if len(mapping) > 1:
                new_cls = mapping[1]
                if new_cls is not None:
                    cls = new_cls
            if len(mapping) > 2:
                gen = mapping[2]

            log.debug("  text %r", data)
            tdata = gen(data)
            log.debug("  result %r", tdata)
            try:
                if hasattr(cls, "Parse"):
                    obj = cls.Parse(tdata)
                else:
                    obj = cls(tdata)
            except TypeError:
                log.error(
                    "Error generating %r instance for attribute "
                    "%r. Perhaps it does not take at least one "
                    "argument in its constructor / initializer or "
                    "implement 'Parse'?", cls.__name__, attr)
                raise
            log.debug("  object %r", obj)
            setattr(self, attr, obj)