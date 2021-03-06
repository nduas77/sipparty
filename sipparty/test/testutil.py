"""tutil.py

Unit tests for sipparty utilities.

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
from __future__ import absolute_import

import logging
from six import (add_metaclass, exec_, next, PY2)
from weakref import ref
from ..util import (
    AsciiBytesEnum, bglobals_g, CCPropsFor, class_or_instance_method, Enum,
    FirstListItemProxy, Singleton, SingletonType, WeakMethod, WeakProperty)
from .base import SIPPartyTestCase

log = logging.getLogger(__name__)


class TestUtil(SIPPartyTestCase):

    def testEnum(self):
        en = Enum(("cat", "dog", "aardvark", "mouse"))

        aniter = en.__iter__()
        self.assertEqual(next(aniter), "cat")
        self.assertEqual(next(aniter), "dog")
        self.assertEqual(next(aniter), "aardvark")
        self.assertEqual(next(aniter), "mouse")
        self.assertRaises(StopIteration, lambda: next(aniter))

        self.assertEqual(en[0], "cat")
        self.assertEqual(en[1], "dog")
        self.assertEqual(en[2], "aardvark")
        self.assertEqual(en[3], "mouse")

        self.assertEqual(en.index("cat"), 0)
        self.assertEqual(en.index("dog"), 1)
        self.assertEqual(en.index("aardvark"), 2)
        self.assertEqual(en.index("mouse"), 3)

        self.assertEqual(en[1:3], ["dog", "aardvark"])

    def testBytesEnum(self):

        if not PY2:
            self.assertRaises(TypeError, lambda: AsciiBytesEnum(('cat',)))
            self.assertRaises(
                TypeError, lambda: AsciiBytesEnum(
                    (b'cat',), aliases={'cat': b'cat'}))
        be = AsciiBytesEnum(
            (b'cat', b'dog'), aliases={b'CAT': b'cat'})
        self.assertTrue(b'cat' in be)
        self.assertEqual(b'cat', be.cat)
        self.assertTrue(hasattr(be, 'cat'))
        self.assertTrue(hasattr(be, 'CAT'))

    def testb_globals(self):

        a_ascii_enum = AsciiBytesEnum((b'a', b'c'))
        a_normal_enum = Enum(('a', 'b'))
        a_normal_bytes_var = b'bytes'
        a_normal_string_var = 'string'

        gdict = bglobals_g(locals())
        self.assertTrue(b'a_ascii_enum.a' in gdict, gdict)
        self.assertTrue(b'a_ascii_enum.c' in gdict, gdict)
        self.assertTrue('a_normal_enum.a' in gdict, gdict)
        self.assertTrue('a_normal_enum.b' in gdict, gdict)
        # Bytes values have their keys converted to bytes also.
        self.assertTrue(b'a_normal_bytes_var' in gdict, gdict)
        self.assertTrue('a_normal_string_var' in gdict, gdict)

    def testSingleton(self):

        s1 = Singleton(singleton='a')
        s2 = Singleton(singleton='a')
        self.assertTrue(s1 is s2)

        s3 = Singleton()
        s4 = Singleton()
        self.assertTrue(s3 is s4)
        self.assertFalse(s3 is s1)

        log.info('Check that a Singleton subclass with no __init__ works.')

        class SingletonSubclass(Singleton):
            pass

        ss1 = SingletonSubclass()
        ss2 = SingletonSubclass()
        self.assertIs(ss1, ss2)

        log.info(
            'Check we get a TypeError if attempting to use an unrelated '
            'metaclass on a subclass of Singleton (standard python behaviour)')

        class NewBadMetaclass(type):
            pass

        self.assertRaises(
            TypeError, NewBadMetaclass, 'BadSingletonSubclass', (Singleton,),
            {})

        log.info('Can we make a metaclass that is OK with Singleton, with six')

        class SubMetaclass(SingletonType):
            pass

        @add_metaclass(SubMetaclass)
        class SingletonSubclass1(Singleton):
            pass

        sing = SingletonSubclass1()
        sing1 = SingletonSubclass1()
        self.assertIs(sing, sing1)
        self.assertIsNot(sing, ss1)

        # Because six uses a class decorator, the SingletonSubclass1 above is
        # actually created twice. The first time before the decorator is
        # called, i.e. the class SingletonSubclass1() line. This is created by
        # a call to the SingletonType.__new__ method because the metaclass is
        # inherited from SingletonSubclass1's base Singleton. However, then six
        # creates a new version of SingletonSubclass1 by calling
        # SubMetaclass.__new__() and passes in info it scraped from the initial
        # creation. SingletonType doesn't really support this, which we test
        # below, but there's an exception when this is triggered by six as that
        # will be common! In this case the initial creation is deleted.
        log.info('Check attempting to create the same type fails.')
        cmd = ("""
class SingletonSubclass1(Singleton):
    __metaclass__ = SingletonType
""" if PY2 else """
class SingletonSubclass1(Singleton, metaclass=SingletonType):
    pass
""")
        with self.assertRaises(RuntimeError):
            exec_(cmd)

    def testCumulativeProperties(self):

        @add_metaclass(CCPropsFor(("CPs", "CPList", "CPDict")))
        class CCPTestA(object):
            CPs = Enum((1, 2))
            CPList = [1, 2]
            CPDict = {1: 1, 2: 2}

        class CCPTestB(CCPTestA):
            CPs = Enum((4, 5))
            CPList = [4, 5]
            CPDict = {4: 4, 3: 3}

        class CCPTest1(CCPTestB):
            CPs = Enum((3, 2))
            CPList = [3, 2]
            CPDict = {2: 2, 3: 5}

        self.assertEqual(CCPTestA.CPs, Enum((1, 2)))
        self.assertEqual(CCPTestB.CPs, Enum((1, 2, 4, 5)))
        self.assertEqual(CCPTest1.CPs, Enum((1, 2, 3, 4, 5)))

        self.assertEqual(CCPTestA.CPDict, {1: 1, 2: 2})
        self.assertEqual(CCPTestB.CPDict, {1: 1, 2: 2, 3: 3, 4: 4})
        self.assertEqual(CCPTest1.CPDict, {1: 1, 2: 2, 3: 5, 4: 4})

        # Expect the order of the update to start with the most nested, then
        # gradually get higher and higher.
        self.assertEqual(CCPTest1.CPList, [1, 2, 4, 5, 3])

    def test_single_cumulative_prop(self):

        log.info(
            'Check we can create a class with cumulative properties metaclass '
            'with just one property specified, as a string')

        @add_metaclass(CCPropsFor("CPs"))
        class CCPTestA(object):
            CPs = Enum((1, 2))

        class CCPTestB(CCPTestA):
            CPs = Enum((4, 5))

        self.assertEqual(CCPTestB.CPs, Enum((1, 2, 4, 5)))

    def testClassOrInstance(self):

        class MyClass(object):

            @class_or_instance_method
            def AddProperty(self, prop, val):
                setattr(self, prop, val)

        inst = MyClass()
        MyClass.AddProperty("a", 1)
        inst.AddProperty("b", 2)
        MyClass.a == 1
        self.assertRaises(AttributeError, lambda: MyClass.b)
        self.assertEqual(inst.a, 1)
        self.assertEqual(inst.b, 2)

    def test_list_attribute(self):
        for bad_attr_name in (1, None):
            log.info(
                'Check bad list attribute for FirstListItemProxy %r',
                bad_attr_name)
            self.assertRaises(TypeError, FirstListItemProxy, bad_attr_name)

        if not PY2:
            for bad_attr_name in (b'hi',):
                log.info(
                    'Check bad list attribute for FirstListItemProxy %r',
                    bad_attr_name)
                self.assertRaises(TypeError, FirstListItemProxy, bad_attr_name)

        class ClassWithListAndFirstListItemProps(object):
            first_of_my_list = FirstListItemProxy('my_list')

        obj = ClassWithListAndFirstListItemProps()

        log.info('Check AttributeError raised for None and missing lists')
        self.assertRaises(AttributeError, getattr, obj, 'first_of_my_list')
        for attr_error_obj in ([], None):
            obj.my_list = attr_error_obj
            self.assertRaises(AttributeError, getattr, obj, 'first_of_my_list')

        log.info('Check TypeError when attempting to use a non-list list.')
        for bad_type_object in (1, {'a:': 1}):
            obj.my_list = bad_type_object
            self.assertRaises(TypeError, getattr, obj, 'first_of_my_list')

        log.info('Check first item in some lists')
        for list_obj in ([1, 2, 3], [{'a': 2, 'c': 3}, None, None], [None]):
            obj.my_list = list_obj
            self.assertIs(obj.first_of_my_list, list_obj[0])

    def test_weak_property(self):

        class Parent(object):
            pass

        class Child(object):
            parent = WeakProperty('parent')

        pp = Parent()
        cc = Child()
        cc.parent = pp
        self.assertIs(cc.parent, pp)
        del pp
        self.assertIs(cc.parent, None)

    def test_weak_method(self):

        results = []

        class MyClass(object):
            def do_something(self):
                results.append(1)

        myc = MyClass()
        wmth = WeakMethod(myc, 'do_something')
        wc = ref(myc)
        self.assertIsNotNone(wc())
        wmth()
        self.assertEqual(results, [1])
        del myc
        self.assertIsNone(wc())
        wmth()
        self.assertEqual(results, [1])
