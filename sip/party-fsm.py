"""party-fsm.py

Implements an `FSM` for use with sip party. This provides a generic way to
implement arbitrary state machines, with easy support for timers.

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
import logging

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)


class FSMError(Exception):
    pass


class UnexpectedInput(FSMError):
    pass


class Timer(object):

    def __init__(self):
        super(Timer, self).__init__(self)


class FSM(object):

    KeyNewState = "new state"
    KeyAction = "action"
    KeyStartTimers = "start timers"
    KeyStopTimers = "stop timers"

    NextFSMNum = 1

    def __init__(self, name=None, asynchronous_timers=False):
        """name: a name for this FSM for debugging purposes.
        """
        super(FSM, self).__init__()

        if name is None:
            name = str(self.__class__.NextFSMNum)
            self.__class__.NextFSMNum += 1

        self._fsm_name = name
        self._fsm_transitions = {}
        self._fsm_state = None
        self._fsm_timers = {}
        self._fsm_use_async_timers = asynchronous_timers

        # Asynchronous timers are not yet implemented.
        assert not self._fsm_use_async_timers

    def addTransition(self, old_state, input, new_state, action=None,
                      start_timers=None, stop_timers=None):
        if old_state not in self._fsm_transitions:
            self._fsm_transitions[old_state] = {}

        state_trans = self._fsm_transitions[old_state]

        if input in state_trans:
            log.debug(self)
            raise ValueError(
                "FSM %r already has a transition for input %r into state "
                "%r." %
                self._fsm_name, input, old_state)

        result = {}
        state_trans[input] = result
        result[self.KeyNewState] = new_state
        result[self.KeyAction] = action

        for tlist, key in (
                (start_timers, self.KeyStartTimers),
                (stop_timers, self.KeyStopTimers)):
            if tlist is not None:
                for tname in tlist:
                    if tname not in self._fsm_timers:
                        raise ValueError()
                result[key] = tlist
            else:
                result[key] = []

        # For convenience assume that the first transition set tells us the
        # initial state.
        if self._fsm_state is None:
            self.setState(old_state)

        log.debug("%r: %r -> %r", old_state, input, result[self.KeyNewState])

    def setState(self, state):
        if state not in self._fsm_transitions:
            raise ValueError(
                "FSM %r has no state %r so it cannot be set." %
                self._fsm_name, state)
        self._fsm_state = state

    def addTimer(self, timer_name, period, action):
        assert 0

    def hit(self, input):
        trans = self._fsm_transitions[self._fsm_state]
        if input not in trans:
            raise UnexpectedInput(
                "Input %r to %r %r (current state %r)." %
                (input, self.__class__.__name__, self._fsm_name,
                 self._fsm_state))
        res = trans[input]
        log.debug("%r: %r -> %r", self._fsm_state, input, res)
        self._fsm_state = res[self.KeyNewState]

    def checkTimers(self):
        """`checkTimers`
        """
        assert not self._fsm_use_async_timers

    @property
    def state(self):
        return self._fsm_state

    def __str__(self):
        return "\n".join([line for line in self._fsm_strgen()])

    def _fsm_strgen(self):
        yield "{0!r} {1!r}:".format(self.__class__.__name__, self._fsm_name)
        if len(self._fsm_transitions) == 0:
            yield "  (No states or transitions.)"
        for old_state, transitions in self._fsm_transitions.iteritems():
            yield "  {0!r}:".format(old_state)
            for input, result in transitions.iteritems():
                yield "    {0!r} -> {1!r}".format(
                    input, result[self.KeyNewState])
            yield ""
        yield "Current state: %r" % self._fsm_state

if __name__ == "__main__":
    import unittest
    logging.basicConfig(level=logging.DEBUG)

    class TestFSM(unittest.TestCase):

        def testSimple(self):
            nf = FSM(name="testfsm")
            self.assertEqual(
                str(nf),
                "'FSM' 'testfsm':\n"
                "  (No states or transitions.)\n"
                "Current state: None")

            nf.addTransition("initial", "start", "starting")
            nf.addTransition("starting", "start", "starting")
            nf.addTransition("starting", "start_done", "running")
            nf.addTransition("running", "stop", "stopping")
            nf.addTransition("stopping", "stop", "stopping")
            nf.addTransition("stopping", "stop_done", "initial")
            self.assertEqual(
                str(nf),
                "'FSM' 'testfsm':\n"
                "  'stopping':\n"
                "    'stop_done' -> 'initial'\n"
                "    'stop' -> 'stopping'\n"
                "\n"
                "  'running':\n"
                "    'stop' -> 'stopping'\n"
                "\n"
                "  'initial':\n"
                "    'start' -> 'starting'\n"
                "\n"
                "  'starting':\n"
                "    'start' -> 'starting'\n"
                "    'start_done' -> 'running'\n"
                "\n"
                "Current state: 'initial'")

            nf.hit("start")
            self.assertEqual(nf.state, "starting")
            self.assertRaises(UnexpectedInput, lambda: nf.hit("stop"))

    unittest.main()
