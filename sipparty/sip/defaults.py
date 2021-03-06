"""defaults.py

Defaults for SIP

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
from ..transport import SOCK_TYPE_IP_NAMES
from .prot import protocols

# Enable useports to ensure that the otherwise implicit 5060 port is always
# explicitly sent in messages.
#
# useports = False
port = 5060
sipprotocol = getattr(protocols, 'SIP/2.0')

transport = SOCK_TYPE_IP_NAMES.UDP
scheme = b'sip'
max_forwards = 70
