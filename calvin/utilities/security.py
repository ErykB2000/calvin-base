# -*- coding: utf-8 -*-

# Copyright (c) 2015 Ericsson AB
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import requests
import json
import string
try:
    import OpenSSL.crypto
    HAS_OPENSSL = True
except:
    HAS_OPENSSL = False
try:
    import pyrad.packet
    from pyrad.client import Client
    from pyrad.dictionary import Dictionary
    HAS_PYRAD = True
except:
    HAS_PYRAD = False

from calvin.utilities.calvinlogger import get_logger
from calvin.utilities import calvinconfig

_conf = calvinconfig.get()
_log = get_logger(__name__)

#default timeout
TIMEOUT=5

STUB=False

def security_modules_check():
    if _conf.get("security","security_conf") or _conf.get("security","security_policy"):
        # Want security
        if not HAS_OPENSSL:
            # Miss open ssl
            _log.error("Install openssl to allow verification of signatures and certificates")
            return False
            _conf.get("security","security_conf")['authentication_method']
        if _conf.get("security","security_conf")['authentication_method'] == "radius" and not HAS_PYRAD:
            _log.error("Install pyrad to use radius server as authentication method.")
            return False
    return True


class Security(object):
    def __init__(self):
        _log.debug("Security:_init_")
        self.sec_conf = _conf.get("security","security_conf")
        self.sec_policy = _conf.get("security","security_policy")
        self.principal = {}

    def set_principal(self, principal):
        if STUB:
            return True
        else:
            _log.debug("Security: set_principal %s" % principal)
            if not isinstance(principal, dict):
                return False
            # Make sure all principal values are lists
            self.principal = {k: list(v) if isinstance(v, (list, tuple, set)) else [v]
                                for k, v in principal.iteritems()}

    def authenticate_principal(self):
        if STUB:
            return True
        _log.debug("Security:authenticate_principal")
        if self.sec_conf['authentication_method'] == "local_file":
            _log.debug("local file authentication method chosen")
            return self.authenticate_using_local_database()
        if self.sec_conf['authentication_method'] == "radius":
            if not HAS_PYRAD:
                _log.error("Install pyrad to use radius server as authentication method.\n" +
                            "NB! NO AUTHENTICATION USED")
                return False
            _log.info("Radius authtentication method chosen")
            return self.authenticate_using_radius_server()
        _log.info("No security config, so authentication disabled")
        return True


    def authenticate_using_radius_server(self):
        if self.principal['user']:
            # FIXME hardcoded secret
            srv=Client(server="localhost", secret="testing123",
                    dict=Dictionary("dicts/dictionary", "dicts/dictionary.acc"))
            req=srv.CreateAuthPacket(code=pyrad.packet.AccessRequest,
                    User_Name=self.principal['user'][0],
                    NAS_Identifier="localhost")
            req["User-Password"]=req.PwCrypt(self.principal['password'][0])
            # FIXME is this over socket? then we should not block here
            reply=srv.SendPacket(req)
            _log.debug("Attributes returned by server:")
            for i in reply.keys():
                _log.debug("%s: %s" % (i, reply[i]))
            if reply.code==pyrad.packet.AccessAccept:
                _log.debug("access accepted")
                return True
            else:
                _log.debug("access denied")
                return False
        _log.debug("No username supplied")
        return False

    def authenticate_using_local_database(self):
        if 'authentication_local_users' not in self.sec_conf:
            return False
        d = self.sec_conf['authentication_local_users']
        if 'user' in self.principal and self.principal['user'][0] in d.keys():
            if d[self.principal['user'][0]] == self.principal['password'][0]:
                _log.debug("found user: %s",self.principal['user'][0])
                return True
            else:
                _log.debug("incorrect username or password")
                return False
        else:
            _log.debug("No username supplied in principal %s" % self.principal)
            return False

    def check_security_actor_requirements(self, requires):
        if STUB:
            return True
        _log.debug("Security:check_security_actor_requirements")
        if self.sec_conf and self.sec_conf['access_control_enabled'] == "True":
            for req in requires:
                if not self.check_security_policy_actor(req, "user", self.principal):
                    return False
        #no security config, so access control is disabled
        return True

    def check_security_policy_actor(self, req, principal_type, principal):
        """ Checks that the requirement is allowed by the security policy """
        if STUB:
            return True
        _log.debug("Security:check_security_policy_actor")
        #Calling function shall already have checked that self.sec_conf exist
        #If the resource is of type calvinsys.media.camera.lense
        if "." in req:
            #create list, e.g., ['calvinsys','media','camera','lense']
            temp = req.split(".")
            while len(temp) >0:
                temp2 = '.'.join(temp)
                # Satisfied when one principal match in one policy
                for plcy in [p for p in self.sec_policy.values() if temp2 in p['resource']]:
                    if any([principal_name in plcy['principal'][principal_type]
                                for principal_type, principal_names in principal.iteritems()
                                if principal_type in plcy['principal']
                                for principal_name in principal_names]):
                        _log.debug("found a match")
                        return True
                #Let's go up in hierarchy, e.g. if we found no policy for calvinsys.media.camera
                #let's now try calvinsys.media instead
                temp.pop()
            #The user is not in the list of allowed users for the resource
            _log.debug("the principal does not have access rights to resource: %s" % req)
            return False
        #Special handling for access only to execution in runtime, but 
        #without access to any particular resource
        elif req == "runtime":
            # Satisfied when one principal match in one policy
            for plcy in [p for p in self.sec_policy.values() if "runtime" in p['resource']]:
                if any([principal_name in plcy['principal'][principal_type]
                            for principal_type, principal_names in principal.iteritems()
                            if principal_type in plcy['principal']
                            for principal_name in principal_names]):
                    _log.debug("found a match for runtime")
                    return True

        #The user is not in the list of allowed users for the resource
        return False

    @staticmethod
    def verify_signature_get_files(filename, skip_file=False):
        if STUB:
            return True
        # Get the data
        sign_filename = filename + ".sign"
        cert_filename = filename + ".cert"
        cert_content = ""
        sign_content = ""
        file_content = ""
        try:
            with open(cert_filename, 'rt') as f:
                cert_content = f.read()
        except:
            return None
        try:
            with open(sign_filename, 'rt') as f:
                sign_content = f.read()
        except:
            return None
        if not skip_file:
            try:
                with open(filename, 'rt') as f:
                    file_content = f.read()
            except:
                return None
        return {'cert': cert_content, 'sign': sign_content, 'file': file_content}

    def verify_signature(self, file, flag):
        content = Security.verify_signature_get_files(file)
        if content:
            return self.verify_signature_content(content, flag)
        else:
            return False

    def verify_signature_content(self, content, flag):
        if STUB:
            return True
        _log.debug("Security: verify_signature")
        if not self.sec_conf:
            _log.debug("no signature verificate required")
            return True

        if flag not in ["application", "actor"]:
            # TODO add component verification
            raise NotImplementedError

        # loop through the policies until one is found that applies to the principal
        # Verification OK if sign and cert OK for any principal matching policy
        for plcy in self.sec_policy.values():
            _log.debug("Security: verify_signature policy: %s\nprincipal: %s" % (plcy, self.principal))
            if any([principal_name in plcy['principal'][principal_type]
                        for principal_type, principal_names in self.principal.iteritems()
                        if principal_type in plcy['principal'] for principal_name in principal_names]):
                _log.debug("found a policy with matching principal:" % plcy)
                if (flag + '_signature') in plcy:
                    if self.verify_signature_and_certificate(content, plcy, flag):
                        return True
        _log.error("verification of %s signature failed" % flag)
        return False

    def verify_signature_and_certificate(self, content, plcy, flag):
        if STUB:
            return True

        if plcy[flag + '_signature'] == "__unsigned__":
            _log.debug("%s is allowed unsigned" % flag)
            return True

        if not HAS_OPENSSL:
            _log.error("Install openssl to allow verification of signatures and certificates")
            _log.error("verification of %s signature failed" % flag)
            return False

        _log.debug("Security:verify_signature_and_certificate")
        try:
            cert = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM, content['cert'])
            #let's see if the certificate is stored in the truststore (name is <hash(CN)>.0)
            trusted_cert = self.sec_conf['signature_trust_store'] + format(cert.subject_name_hash(),'x') + ".0"
            with open(trusted_cert, 'rt') as f:
                string_trusted_cert = f.read()
                trusted_cert = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM, string_trusted_cert)
                if self.check_signature_policy(trusted_cert, flag, plcy):
                    try:
                        OpenSSL.crypto.verify(trusted_cert, content['sign'], content['file'], 'sha256')
                        _log.debug("%s signature correct" % flag)
                        return True
                    except Exception as e:
                        _log.exception("OpenSSL verification error")
                        _log.error("verification of %s signature failed" % flag)
                        return False
                else:
                    _log.debug("signature policy not fulfilled")
                    _log.error("verification of %s signature failed" % flag)
                    return False
        except Exception as e:
            _log.exception("error opening one of the needed certificates")
            _log.error("verification of %s signature failed" % flag)
            return False

    def check_signature_policy(self, cert, flag, plcy):
        """ Checks that if the signer is allowed by the security policy """
        if STUB:
            return True
        _log.debug("Security:check_signature_policy")
        if flag=="application":
            if 'application_signature' in plcy:
                if cert.get_issuer().CN not in plcy['application_signature']:
                    _log.debug("application signer not allowed")
                    return False
            else:
                _log.debug("no application_signature element, unsigned applications allowed")
        elif flag=="actor":
            if 'actor_signature' in plcy:
                if cert.get_issuer().CN not in plcy['actor_signature']:
                    _log.debug("actor signer not allowed")
                    return False
            else:
                _log.debug("no actor_signature element, unsigned applications allowed")
        return True


