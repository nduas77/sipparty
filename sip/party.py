"""party.py

Implements the `Party` object.

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
import six
import socket
import logging
import copy
import weakref
import re
import time
import _util
import transport
import siptransport
import prot
import components
import scenario
import defaults
import request
from message import (Message, Response)
import transform
import message
import vb
import parse

__all__ = ('Party',)

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)


class PartyException(Exception):
    "Generic party exception."


class NoConnection(PartyException):
    """Exception raised when the connection cannot be created to a remote
    contact, or it is lost."""


class UnexpectedState(PartyException):
    "The party entered an unexpected state."


class Timeout(PartyException):
    "Timeout waiting for something to happen."


def NewAOR():
    newaor = defaults.AORs.pop(0)
    defaults.AORs.append(newaor)
    return newaor


class PartyMetaclass(type):
    def __init__(cls, name, bases, dict):
            super(PartyMetaclass, cls).__init__(name, bases, dict)

            # Add any predefined transitions.
            if hasattr(cls, "ScenarioDefinitions"):
                cls.SetScenario(cls.ScenarioDefinitions)


@six.add_metaclass(PartyMetaclass)
class Party(vb.ValueBinder):
    """A party in a sip call, aka an endpoint, caller or callee etc.
    """

    #
    # =================== CLASS INTERFACE ====================================
    #
    vb_bindings = [
        ("aor",
         "_pt_outboundMessage.FromHeader.field.value.uri.aor"),
        ("_pt_transport.localAddressHost",
         "_pt_outboundMessage.ContactHeader.field.value.uri.aor.host"),
        ("_pt_transport.localAddressPort",
         "_pt_outboundMessage.ContactHeader.field.value.uri.aor.port")
    ]
    vb_dependencies = [
        ("scenario", ["state"]),
        ("_pt_transport", ["localAddress"])]

    Scenario = None

    @classmethod
    def SetScenario(cls, scenario_definition):
        if cls.Scenario is not None:
            raise AttributeError(
                "Scenario for class %r is already set." % (cls.__name__,))
        cls.Scenario = scenario.ScenarioClassWithDefinition(
            cls.__name__, scenario_definition)

    #
    # =================== INSTANCE INTERFACE =================================
    #
    aor = _util.DerivedProperty("_pt_aor")

    def __init__(self, username=None, host=None, displayname=None):
        """Create the party.
        """
        super(Party, self).__init__()

        self._pt_waitingMessage = None

        self.aor = NewAOR()
        if username is not None:
            self.aor.username = username
        if host is not None:
            self.aor.host = host

        # Set up the transport.
        self._pt_transport = siptransport.SipTransportFSM()

        # Currently don't do listen until required to.
        # self._pt_transport.listen()
        self._pt_transport.messageConsumer = _util.WeakMethod(
            self, "_pt_messageConsumer")

        # Set up the scenario.
        if self.Scenario is not None:
            self.scenario = self.Scenario(delegate=self)
            self.scenario.actionCallback = _util.WeakMethod(
                self, "scenarioActionCallback")

        # Set up the transform.
        if not hasattr(self, "transform"):
            self.transform = transform.default

    def hit(self, input, *args, **kwargs):
        self.scenario.hit(input, *args, **kwargs)

    def waitUntilState(self, state,
                       error_state=None, timeout=None, poll_interval=0.001):
        for check_state in (state, error_state):
            if check_state is not None and check_state not in self.States:
                raise AttributeError(
                    "%r instance has no state %r." % (
                        self.__class__.__name__, check_state))

        start_time = time.time()
        while True:
            state_now = self.state
            if state_now == state:
                return

            if error_state is not None and state_now == error_state:
                raise UnexpectedState(
                    "%r instance has entered the error state %r while "
                    "waiting for state %r." % (
                        self.__class__.__name__, error_state, state))

            if timeout is not None and (time.time() - start_time > timeout):
                raise Timeout(
                    "%r instance has timed out (waited %r seconds) while "
                    "waiting for state %r." % (
                        self.__class__.__name__, timeout, state))
            time.sleep(poll_interval)

    #
    # =================== INTERNAL ===========================================
    #
    def __getattr__(self, attr):

        if attr == "States":
            try:
                return getattr(self.Scenario, attr)
            except AttributeError:
                raise AttributeError(
                    "%r instance has no attribute %r as it is not "
                    "configured with a Scenario." % (
                        self.__class__.__name__, attr))

        internalSendPrefix = "_send"
        if attr.startswith(internalSendPrefix):
            message = attr.replace(internalSendPrefix, "", 1)
            try:
                send_action = _util.WeakMethod(
                    self, "_pt_send", static_args=[message])
            except:
                log.exception("")
                raise
            return send_action

        internalReplyPrefix = "_reply"
        if attr.startswith(internalReplyPrefix):
            message = attr.replace(internalReplyPrefix, "", 1)
            try:
                send_action = _util.WeakMethod(
                    self, "_pt_reply", static_args=[message])
            except:
                log.exception("")
                raise
            return send_action

        scn = self.scenario
        if scn is not None and attr in scn.Inputs:
            try:
                scn_action = _util.WeakMethod(
                    scn, "hit", static_args=[attr])
                return scn_action
            except:
                log.exception("")
                raise

        try:
            return super(Party, self).__getattr__(attr)
        except AttributeError:
            log.debug(
                "scenario inputs: %r",
                scn.Inputs if scn is not None else None)
            raise AttributeError(
                "{self.__class__.__name__!r} instance has no attribute "
                "{attr!r}."
                "".format(**locals()))

    def _pt_messageConsumer(self, message):
        log.debug("Received a %r message.", message.type)
        self.scenario.hit(message.type, message)

    def _pt_send(self, message_type, callee, contactAddress=None):
        log.debug("Send message of type %r to %r.", message_type, callee)

        # Callee can be overridden with various different types of object.
        if isinstance(callee, components.AOR):
            calleeAOR = callee
        elif hasattr(callee, "aor"):
            calleeAOR = callee.aor
        else:
            calleeAOR = components.AOR.Parse(callee)
        log.debug("calleeAOR: %r", calleeAOR)

        if contactAddress is None:
            if hasattr(callee, "localAddress"):
                contactAddress = callee.localAddress
            else:
                contactAddress = calleeAOR.host.addrTuple()

        if not isinstance(calleeAOR, components.AOR):
            # Perhaps we can make an AOR out of it?
            try:
                calleeAOR = components.AOR.Parse(calleeAOR)
                log.debug("Callee: %r, host: %r.", calleeAOR, calleeAOR.host)
            except TypeError, parse.ParseError:
                raise ValueError(
                    "Message recipient is not an AOR: %r." % callee)

        if self._pt_transport.state != self._pt_transport.States.connected:
            self._pt_transport.connect(contactAddress)
            _util.WaitFor(
                lambda:
                    self._pt_transport.state in
                    (self._pt_transport.States.connected,
                     self._pt_transport.States.error),
                10.0)

        if self._pt_transport.state == self._pt_transport.States.error:
            scn = self.scenario
            if scn is not None:
                scn.reset()
            raise NoConnection(
                "Got an error attempting to connect to %r @ %r." % (
                    calleeAOR, contactAddress))

        msg = getattr(Message, message_type)()
        self._pt_outboundMessage = msg

        msg.startline.uri.aor = calleeAOR
        msg.viaheader.field.transport = transport.SockTypeName(
            self._pt_transport.type)

        self._pt_transport.send(str(msg))

    def _pt_reply(self, message_type, request):
        log.debug("Reply to %r with %r.", request.type, message_type)
        if re.match("\d+$", message_type):
            message_type = int(message_type)
            msg = message.Response(code=message_type)
        else:
            msg = getattr(message.Message, message_type)

        tform = self.transform[request.type][message_type]
        request.applyTransform(msg, tform)

        self._pt_transport.send(str(msg))
