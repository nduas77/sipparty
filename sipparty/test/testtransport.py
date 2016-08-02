"""ttransport.py

Unit tests for the transport code.

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
from socket import (SOCK_STREAM, AF_INET, AF_INET6)
from ..transport import (
    ConnectedAddressDescription, ListenDescription,
    SocketProxy, Transport, IPv6address_re,
    IPv6address_only_re)
from ..util import WaitFor
from .setup import (SIPPartyTestCase)

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


class TestTransport(SIPPartyTestCase):

    def setUp(self):
        super(TestTransport, self).setUp()
        self.data_call_back_call_args = []

    def data_callback(self, from_address, to_address, data):
        self.data_call_back_call_args.append((
            from_address, to_address, data))

    def new_connection(self, local_address, remote_address):
        return True

    def test_ip_addresses(self):
        for ip6_string in (
                b'::1', b'::', b'fe80::1', b'fe80:1:1:1:1:1:1:1',
                b'fe80::aa66:7fff:FE0e:f035', b'fe80::', b'1:2:3:4:5:6:7::'):
            mo = IPv6address_re.match(ip6_string)
            self.assertIsNotNone(mo)
            self.assertEqual(mo.group(0), ip6_string)

            # Should get the same results with an exact match.
            mo = IPv6address_only_re.match(ip6_string)
            self.assertIsNotNone(mo)
            self.assertEqual(mo.group(0), ip6_string)

        for bad_ip6_addr in (
                b'fe80::1::1', b':::', b'1:2:3:4:5:6:7:8:9',
                b'1:2:3::5:6:7:8:9', b'1::3:4:5:6:7:8:9', b'1::3:4:5:6:7:8:',
                b'1:2:3:4:5:6:7::9'):
            mo = IPv6address_only_re.match(bad_ip6_addr)
            self.assertIsNone(mo)

        for contains_ip_addr, offset, length in (
                (b'fe80::aa66:7fff:fe0e:f035%en0', 0, 25),):
            mo = IPv6address_re.match(contains_ip_addr)
            self.assertIsNotNone(mo)
            self.assertEqual(mo.group(0), contains_ip_addr[offset:length])

    def test_transport_data_structures(self):
        log.info('Test transport data structures')
        tp = Transport()
        ad = ConnectedAddressDescription(
            name='0.0.0.0', sock_family=AF_INET, sock_type=SOCK_STREAM,
            remote_name='127.0.0.1', remote_port=54321)
        sp = SocketProxy(local_address=ad, transport=tp)
        tp.add_connected_socket_proxy(sp)
        self.assertEqual(tp.connected_socket_count, 1)

        ad = ConnectedAddressDescription(
            name='0.0.0.0', sock_family=AF_INET, sock_type=SOCK_STREAM,
            remote_name='127.0.0.1', remote_port=54322)
        sp = SocketProxy(local_address=ad, transport=tp)

        log.info('Add second connected socket proxy, make sure it is saved.')
        tp.add_connected_socket_proxy(sp)
        self.assertEqual(tp.connected_socket_count, 2)

        log.info('Check descriptions can deduce some values.')
        ld = ListenDescription(name='1.1.1.1')
        self.assertEqual(ld.sock_family, None)
        ld.deduce_missing_values()
        self.assertEqual(ld.sock_family, AF_INET)

        ld = ListenDescription(name='::1:2:3:4')
        self.assertIs(ld.flowinfo, None)
        self.assertIs(ld.scopeid, None)
        ld.deduce_missing_values()
        self.assertEqual(ld.sock_family, AF_INET6)
        self.assertEqual(ld.flowinfo, 0)
        self.assertEqual(ld.scopeid, 0)

    def test_listen_address_create(self):
        log.info('ListenDescription requires a port argument')

        sock_family = AF_INET
        sock_type = SOCK_STREAM

        log.info('Get a standard (IPv4) listen address from the transport.')
        tp = Transport()
        self.assertRaises(TypeError, tp.listen_for_me, 'not-a-callable')
        self.assertRaises(
            ValueError, tp.listen_for_me, self.data_callback,
            sock_family=sock_family,
            sock_type='not-sock-type')

        laddr = tp.listen_for_me(
            self.data_callback, sock_family=sock_family, sock_type=sock_type)
        self.assertTrue(isinstance(laddr, ListenDescription), laddr)

        log.info('Listen a second time and reuse existing')
        laddr2 = tp.listen_for_me(
            self.data_callback, sock_family=sock_family, sock_type=sock_type)
        self.assertEqual(laddr2.sockname_tuple, laddr.sockname_tuple)

        log.info('Release address once')
        tp.release_listen_address(laddr)

        log.info('Release address twice')
        tp.release_listen_address(laddr)
        log.info(
            'Release address three times and get an exception as it has now '
            'been freed.')

        self.skipTest("Can't do the remaining until fix the reuse bug.")

        log.info("Listen a third time but use a different socket")
        laddr3 = tp.listen_for_me(
            self.data_callback, sock_family=sock_family, sock_type=sock_type,
            reuse_socket=False)

        log.info('Listening on ports %d', laddr.port)

        self.assertRaises(KeyError, tp.release_listen_address, laddr)

        log.info('Release third listen address')
        tp.release_listen_address(laddr3)
        self.assertRaises(KeyError, tp.release_listen_address, laddr3)

    def test_listen_address_receive_data(self):
        sock_family = AF_INET

        log.info('Get a listen address')
        tp = Transport()
        laddr_desc = tp.listen_for_me(
            self.data_callback, sock_family=sock_family)

        log.info('Get send from address connected to the listen address')
        conn_sock_proxy = tp.get_send_from_address(
            sock_family=sock_family,
            remote_name='127.0.0.1', remote_port=laddr_desc.port,
            data_callback=self.data_callback)

        self.assertIs(conn_sock_proxy.transport, tp)

        # At this point we should have two connected sockets if TCP, one on
        # UDP. That's because we only detect a new UDP 'connection' when we
        # have first received data on it.
        self.assertEqual(tp.connected_socket_count, 1)

        log.info('Reget the send from address and check it\'s the same one.')
        second_conn_sock_proxy = tp.get_send_from_address(
            remote_name='127.0.0.1', remote_port=laddr_desc.port,
            data_callback=self.data_callback)

        self.assertIs(conn_sock_proxy, second_conn_sock_proxy)
        del second_conn_sock_proxy

        self.assertEqual(tp.connected_socket_count, 1)

        conn_sock_proxy.send(b'hello laddr_desc')
        WaitFor(lambda: len(self.data_call_back_call_args) > 0)

        fromaddr, toaddr, data = self.data_call_back_call_args.pop()
        self.assertEqual(data, b'hello laddr_desc')
        self.assertEqual(tp.connected_socket_count, 2)

        # Type Error because using a bad remote_port type.
        self.assertRaises(
            TypeError, tp.get_send_from_address,
            remote_port=conn_sock_proxy.local_address,
            data_callback=self.data_callback)

        log.info('Send data back on the new connection.')
        lstn_conn_sock_proxy = tp.get_send_from_address(
            remote_name=conn_sock_proxy.local_address.name,
            remote_port=conn_sock_proxy.local_address.port,
            data_callback=self.data_callback)

        lstn_conn_sock_proxy.send(b'hello other')
        WaitFor(lambda: len(self.data_call_back_call_args) > 0)
        fromaddr, toaddr, data = self.data_call_back_call_args.pop()
        self.assertEqual(data, b'hello other')

    def test_parsing_ip_addresses(self):

        for bad_name in ('not-an-ip', 'fe80::1::1'):
            laddr = ListenDescription(name=bad_name)
            self.assertRaises(ValueError, laddr.address_as_tuple)

        for inp, out in (
                ('127.0.0.1', (127, 0, 0, 1)),
                ('0.0.0.0', (0, 0, 0, 0)),
                ('fe80:12:FFFF::', (0xfe80, 0x12, 0xffff, 0, 0, 0, 0, 0)),
                ('fe80::1', (0xfe80, 0, 0, 0, 0, 0, 0, 1)),
                ('::1', (0, 0, 0, 0, 0, 0, 0, 1)),
                ('::', (0, 0, 0, 0, 0, 0, 0, 0)),):
            laddr = ListenDescription(name=inp)
            self.assertEqual(laddr.address_as_tuple(), out)
