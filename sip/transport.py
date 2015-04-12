"""transport.py

Implements a transport layer.

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
import socket
import threading
import time
import logging
import _util
import fsm

log = logging.getLogger(__name__)


class BadNetwork(Exception):
    pass


def SockFamilyName(family):
    if family == socket.AF_INET:
        return "IPv4"
    if family == socket.AF_INET6:
        return "IPv6"
    assert family in (socket.AF_INET, socket.AF_INET6)


def SockTypeName(socktype):
    if socktype == socket.SOCK_STREAM:
        return "TCP"
    if socktype == socket.SOCK_DGRAM:
        return "UDP"
    assert socktype in (socket.SOCK_STREAM, socket.SOCK_DGRAM)


def GetBoundSocket(family, socktype, address):

    assert family in (0, socket.AF_INET, socket.AF_INET6)
    assert socktype in (0, socket.SOCK_STREAM, socket.SOCK_DGRAM)

    address = list(address)
    if address[0] is None:
        address[0] = socket.gethostname()

    # family e.g. AF_INET / AF_INET6
    # socktype e.g. SOCK_STREAM
    # Just grab the first addr info if we haven't
    log.debug("getaddrinfo addr:%r port:%r family:%r socktype:%r",
              address[0], address[1], family, socktype)
    addrinfos = socket.getaddrinfo(address[0], address[1], family, socktype)

    if len(addrinfos) == 0:
        raise BadNetwork("Could not find an address to bind to %r." % address)

    _family, _socktype, _proto, _canonname, address = addrinfos[0]

    ssocket = socket.socket(family, socktype)

    def port_generator():
        if address[1] != 0:
            # The port was specified.
            yield address[1]
            return

        # Guess a port.
        yield 5060  # Always try 5060 first.
        for ii in range(15060, 0x10000):
            yield ii

    for port in port_generator():
        try:
            ssocket.bind(address)
            break
        except socket.error:
            pass
    else:
        raise BadNetwork(
            "Couldn't bind to address {address}.".format(
                **locals()))

    return ssocket


class TransportFSM(fsm.FSM):
    """Controls a socket connection
    """

    States = _util.Enum(
        ("disconnected",
         "listening",
         "connecting",
         "connected",
         "error"))
    Inputs = _util.Enum(
        ("connect", "listen", "connected",
         "send",
         "disconnect", "error",
         "reset"))
    Actions = _util.Enum(
        ("createConnect", "attemptConnect",
         "createListen", "startListening", "becomesConnected",
         "send",
         "becomesDisconnected", "error"))

    @classmethod
    def AddClassTransitions(cls):

        S = cls.States
        I = cls.Inputs
        A = cls.Actions
        Add = cls.addTransition

        # Transitions when connecting out.
        Add(S.disconnected, I.connect, S.connecting,  # Start connecting.
            action=A.createConnect,
            start_threads=[A.attemptConnect])
        Add(S.connecting, I.error, S.error,
            action=A.error)
        Add(S.connecting, I.connected, S.connected,
            action=A.becomesConnected)

        # Transitions when being connected to.
        Add(S.disconnected, I.listen, S.listening,
            action=A.createListen,
            start_threads=[A.startListening])
        Add(S.listening, I.error, S.error,
            action=A.error)
        Add(S.listening, I.connected, S.connected,
            action=A.becomesConnected)

        # Actions when in the connected state.
        Add(S.connected, I.send, S.connected,
            action=A.send)
        Add(S.connected, I.error, S.error,
            action=A.becomesDisconnected)
        Add(S.connected, I.disconnect, S.disconnected,
            action=A.becomesDisconnected)

        # Error in error and reset from an error.
        Add(S.error, I.reset, S.disconnected)

        # Start disconnected.
        cls.setState(S.disconnected)

    def __init__(self, *args, **kwargs):

        # The transport FSM is a root level independent FSM that schedules
        # its own work on a background thread, and to do this it uses the
        # asynchronous_timers feature of the FSM class.
        assert ("asynchronous_timers" not in kwargs or
                kwargs["asynchronous_timers"])
        kwargs["asynchronous_timers"] = True
        super(TransportFSM, self).__init__(*args, **kwargs)

        self._tfsm_family = socket.AF_INET
        self._tfsm_type = socket.SOCK_STREAM

        la = self.__dict__["_tfsm_localAddress"] = [None, 0, 0, 0]
        self._tfsm_remoteAddress = None

        self._tfsm_receiveSize = 4096
        self._tfsm_timeout = 2

        self._tfsm_listenSck = None
        self._tfsm_activeSck = None
        self._tfsm_buffer = bytearray()
        self._tfsm_byteConsumer = None

        # BSD (Mac OS X anyway) seems not to propagate an error to an accept
        # call on a socket if you close it from a different thread. So need
        # to use non-blocking sockets so that the accept loop can keep
        # checking whether the socket is still valid.
        self._tfsm_acceptSocketTimeout = 0.1

    # Public properties.
    family = _util.DerivedProperty(
        "_tfsm_family", lambda val: val in (socket.AF_INET, socket.AF_INET6))
    type = _util.DerivedProperty(
        "_tfsm_type",
        lambda val: val in (socket.SOCK_STREAM, socket.SOCK_DGRAM))

    localAddress = _util.DerivedProperty("_tfsm_localAddress")
    localAddressPort = _util.DerivedProperty(
        "_tfsm_localAddressPort",
        lambda val: 0 <= val <= 0xffff)
    localAddressHost = _util.DerivedProperty("_tfsm_localAddressHost")
    byteConsumer = _util.DerivedProperty(
        "_tfsm_byteConsumer",
        lambda val: isinstance(val, collections.Callable))

    def block_until_states(states):
        "This is a descriptor, so don't call it as a method."

        def buse_desc(method):
            def block_until_states_wrapper(self, *args, **kwargs):
                state_now = self.state
                method(self, *args, **kwargs)

                end_states = states
                time_start = _util.Clock()
                time_now = time_start
                while self.state not in end_states:
                    if time_now - time_start > self._tfsm_timeout:
                        self.hit(self.States.error)
                        new_end_states = (self.States.error,)
                        if end_states == new_end_states:
                            # Ahh must do proper exceptions!
                            raise Exception(
                                "help failed to enter error state.")
                        end_states = new_end_states
                        time_start = time_now

                    time.sleep(0.00001)
                    time_now = _util.Clock()

                if self.state not in end_states:
                    # Ahh must do proper exceptions!
                    raise Exception("Timeout reaching end state.")
            return block_until_states_wrapper
        return buse_desc

    # !!! These could be improved.
    @block_until_states((States.error, States.listening))
    def listen(self):
        self.hit(self.Inputs.listen)

    @block_until_states((States.error, States.connecting, States.connected))
    def connect(self, *args, **kwargs):
        self.hit(self.Inputs.connect, *args, **kwargs)

    @block_until_states((States.error, States.disconnected))
    def disconnect(self):
        self.hit(self.Inputs.disconnect)

    @block_until_states((States.disconnected))
    def reset(self):
        self.hit(self.Inputs.reset)

    # ACTIONS ACTIONS ACTIONS ACTIONS ACTIONS ACTIONS ACTIONS ACTIONS ACTIONS
    #
    # These actions are expected to be done synchronously on the main FSM
    # thread, therefore they should not block. Blocking function should be
    # done in the THREADS methods below.
    #
    # They should not be called directly; all interaction with the FSM should
    # be via one of the PUBLIC methods, and in particular the hit() method.
    #
    def createConnect(self, addr_tuple):

        log.debug("Create connect socket destined for %r.", addr_tuple)

        fam = self.family
        typ = self.type
        adr = self._tfsm_localAddress
        prt = self._tfsm_localAddressPort

        explen = 2 if fam == socket.AF_INET else 4

        if len(addr_tuple) != explen:
            self.hit(self.Inputs.error, "Bad address %r for %r socket." %
                     (addr_tuple, SockFamilyName(fam)))
            return

        try:
            self._tfsm_activeSck = GetBoundSocket(fam, typ, adr)
        # Need to add proper exception handling for socket errors here.
        except:
            log.error("Exception hit getting bound socket for connection.")
            self.hit(self.Inputs.error)
            raise

        self._tfsm_remoteAddressTuple = addr_tuple

    def createListen(self):
        try:
            self._tfsm_listenSck = GetBoundSocket(
                self.family, self.type, self._tfsm_localAddress)
        except Exception as exc:
            log.exception("Exception getting passive socket.")
            self.hit(self.Inputs.error,
                     "Exception getting passive socket: %r." % exc)
            return

        # Listen if it's a stream.
        if self._tfsm_listenSck.type == socket.SOCK_STREAM:
            log.debug("Listening for connections.")
            self._tfsm_listenSck.listen(0)

        self._tfsm_listenSck.settimeout(self._tfsm_acceptSocketTimeout)
        log.info(
            "Passive socket created on %r.",
            self._tfsm_listenSck.getsockname())

    def becomesConnected(self):
        "Called when the transport becomes connected"
        self.addFDSource(self._tfsm_activeSck, self._tfsm_dataAvailable)

    def becomesDisconnected(self):
        "Called when the transport goes down."
        self.rmFDSource(self._tfsm_activeSck)
        for sck in (self._tfsm_activeSck, self._tfsm_listenSck):
            if sck is not None:
                sck.close()
        self._tfsm_activeSck = None
        self._tfsm_listenSck = None

    def send(self, data):
        "Send some data."
        datalen = len(data)
        sck = self._tfsm_activeSck

        sent_bytes = sck.send(data)
        if sent_bytes != datalen:
            self.error("Failed to send %d bytes of data." %
                       (datalen - sent_bytes))

    def error(self, msg="unknown error"):
        "We've hit an error."
        self._tfsm_errormsg = msg
        if self._tfsm_listenSck is not None:
            log.debug("Error: close listen socket")
            self._tfsm_listenSck.close()
            self._tfsm_listenSck = None

        if self._tfsm_activeSck is not None:
            log.debug("Error: close active socket")
            self._tfsm_activeSck.close()
            self._tfsm_activeSck = None

        log.error(msg)

    # THREADS THREADS THREADS THREADS THREADS THREADS THREADS THREADS THREADS
    #
    def attemptConnect(self):
        "Attempt to connect out."

        sck = self._tfsm_activeSck
        if sck is None:
            log.debug("Create socket failed, so nothing to do.")
            return

        family = self.family
        sck_type = self.type
        address = self._tfsm_localAddress
        remote_address = self._tfsm_remoteAddressTuple

        # Finish the connect out FSM side, and move on to the accept.

        try:
            self._tfsm_activeSck.connect(self._tfsm_remoteAddressTuple)
        except Exception as exc:
            self.hit(
                self.Inputs.error,
                "Exception connecting to %r: %r." %
                (self._tfsm_remoteAddressTuple, exc))
            return

        self.hit(self.Inputs.connected)

    def startListening(self):

        log.debug("STREAM socket so block to accept a connection.")

        startListen = _util.Clock()
        nextLog = startListen + 1

        while True:
            lsck = self._tfsm_listenSck

            if lsck is None:
                log.debug("Listen has been cancelled.")
                break

            if lsck.type == socket.SOCK_DGRAM:
                raise ValueError("DGRAM socket (UDP) support not "
                                 "implemented.")

            now = _util.Clock()
            if now > nextLog:
                log.debug("Still waiting to accept...")
                nextLog = now + 1

            try:
                conn, addr = lsck.accept()
                log.debug("Connection accepted from %r.", addr)
                self._tfsm_activeSck = conn
                self.hit(self.Inputs.connected)
                break
            except socket.timeout:

                continue
            except Exception as exc:
                log.debug("Exception selecting listen socket", exc_info=True)
                self.hit(self.Inputs.error,
                         "Exception selecting listen socket %r." % exc)
                break

        log.debug("Start listening done.")

    #
    # INTERNAL INTERNAL INTERNAL INTERNAL INTERNAL INTERNAL INTERNAL INTERNAL
    #
    @property
    def _tfsm_localAddress(self):
        for sck in (self._tfsm_activeSck, self._tfsm_listenSck):
            if sck is not None:
                return sck.getsockname()

        la = self.__dict__["_tfsm_localAddress"]
        return (tuple(la[:2]) if self._tfsm_family == socket.AF_INET else
                tuple(la))

    @property
    def _tfsm_localAddressHost(self):
        return self._tfsm_localAddress[0]

    @_tfsm_localAddressHost.setter
    def _tfsm_localAddressHost(self, val):
        self.__dict__["_tfsm_localAddress"][0] = val

    @property
    def _tfsm_localAddressPort(self):
        return self._tfsm_localAddress[1]

    @_tfsm_localAddressPort.setter
    def _tfsm_localAddressPort(self, val):
        la = self.__dict__["_tfsm_localAddress"][1] = val

    def _tfsm_dataAvailable(self, sck):
        """This method is registered when connected with the FSM's thread to
        be called when there is data available on the socket.
        """
        string, address = sck.recvfrom(self._tfsm_receiveSize)
        strlen = len(string)
        log.debug("Received %d bytes from %r.", strlen, address)
        self._tfsm_buffer.extend(bytearray(string))

        if self._tfsm_byteConsumer is None:
            log.debug("No consumer; dumping bytes: %r.", self._tfsm_buffer)
            del self._tfsm_buffer[:]

        else:
            while True:
                bytes_consumed = self._tfsm_byteConsumer(self._tfsm_buffer)
                if bytes_consumed == 0:
                    log.debug("Can consume no more bytes now.")
                    break

                    del self._tfsm_buffer[:bytes_consumed]

        if strlen == 0:
            log.debug("Received 0 bytes: socket has demurely.")
            self.hit(self.Inputs.disconnect)
