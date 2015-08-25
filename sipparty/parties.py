"""parties.py

Implements various convenient `Party` subclasses.

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
from sipparty.sip.dialogs import SimpleCall
from sipparty.media import SingleRTPSession
from sipparty.party import Party


class SingleRTPSessionSimplenParty(Party):
    InviteDialog = SimpleCall
    MediaSession = SingleRTPSession