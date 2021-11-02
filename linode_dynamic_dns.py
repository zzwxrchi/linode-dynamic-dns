#!/usr/bin/env python3
import argparse
import http.client
import ipaddress
import json
import logging
import os
import sys
import time
import urllib.request

__version__ = '0.6.5'

LOGGER = logging.getLogger(__package__)

TIMEOUT = 15

IP_URLS = {4: os.environ.get('IPV4_URL', 'https://ipv4.icanhazip.com'),
           6: os.environ.get('IPV6_URL', 'https://ipv6.icanhazip.com')}

LINODE_API_URL = 'https://api.linode.com/v4'


class LinodeAPI:
    def __init__(self, key):
        self._key = key

    def request(self, method, path, **kwargs):
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {self._key}'
        }
        if 'json' in kwargs:
            data = json.dumps(kwargs['json']).encode()
            headers['Content-Type'] = 'application/json'
        else:
            data = None

        request = urllib.request.Request(
            url=f'{LINODE_API_URL}/{path}',
            headers=headers,
            method=method,
            data=data
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, json.loads(response.read())

    def get_domains(self):
        status, content = self.request('GET', 'domains')
        # TODO: Support pagination
        yield from content['data']

    def get_domain_records(self, domain_id):
        status, content = self.request('GET', f'domains/{domain_id}/records')
        yield from content['data']

    def update_domain_record_target(self, domain_id, record_id, target):
        status, _ = self.request(
            'PUT',
            f'domains/{domain_id}/records/{record_id}',
            json={'target': str(target)}
        )
        if status != 200:
            raise http.client.HTTPException(f'status {status}')

    # create host record if not exist
    def create_domain_host_record(self, domain_id, host, recordType, target):
        status, _ = self.request(
            'POST',
            f'domains/{domain_id}/records',
            json={'name':str(host),
                'type':str(recordType),
                'target':str(target)}
        )
        if status != 200:
            raise http.client.HTTPException(f'status {status}')


def get_ip(version):
    url = IP_URLS[version]
    LOGGER.info(f'url of IPv{version} is: {url}')

    try:
        response = urllib.request.urlopen(url, timeout=TIMEOUT)
    except (OSError, urllib.error.URLError):
        LOGGER.info(f'http error in get_ip({version})')
        return None
        
#    with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
#        if response.status >= 400:
#            raise http.client.HTTPException(f'status {response.status}')

    content = response.read()
    ip = ipaddress.ip_address(content.decode().strip())
    if ip and ip.version == version:
        LOGGER.info(f'Local IPv{version} "{ip}"')
        return ip
    else:
        LOGGER.info(f'No local IPv{version}.')
        return None


def update_dns(api, domain, host):
    domain_id = None
    for d in api.get_domains():
        if d['domain'] == domain:
            domain_id = d['id']
            break

    if domain_id is None:
        print(f'Error: Domain "{domain}" not found')
        sys.exit(1)

    # TODO: Delete invalid records and duplicates
    # Make host list
    hosts = host.split(",")
    local_ip4 = get_ip(4)
    local_ip6 = get_ip(6)

    for h in hosts:
        # if host name (subdomain) don't created in linode
        found = False

        for record in api.get_domain_records(domain_id):
            LOGGER.info(f'Record name: {record["name"]}')

            if record['name'] == h.strip() or (record['name'] == '' and h.strip() == '@'):
                found = True # host name created
                LOGGER.info(f'Seted host: {h} found: {found}, with remote record: {record["name"]}')

                if  record['type'] == 'A':
                    local_ip = local_ip4

                elif  record['type'] == 'AAAA':
                    local_ip = local_ip6

                record_ip = ipaddress.ip_address(record['target'])
                LOGGER.info(f'Remote IPv{record_ip.version} "{record_ip}" target to host: {h}')

                if local_ip and local_ip != record_ip:
                    log_suffix = (f'IPv{local_ip.version} '
                                  f'"{record_ip}" change to "{local_ip}"')
                    LOGGER.info(f'Attempting update of {log_suffix}')
                    api.update_domain_record_target(
                        domain_id, record['id'], local_ip)
                    LOGGER.info(f'Successful update of {log_suffix}')

                break

        if not found and h.strip() != '' and h.strip() != '@':
            LOGGER.info(f'Create new host record')
            # create host name record in linode

            if local_ip4:
                log_suffix = (f'Add new host A record with target {local_ip4}')
                LOGGER.info(f'Attempting: {log_suffix}')
                api.create_domain_host_record(
                    domain_id, h, "A", local_ip4)
                LOGGER.info(f'Successfu: {log_suffix}')
            
            if local_ip6:
                log_suffix = (f'Add new host AAAA record with target {local_ip6}')
                LOGGER.info(f'Attempting: {log_suffix}')
                api.create_domain_host_record(
                    domain_id, h, "AAAA", local_ip6)
                LOGGER.info(f'Successfu: {log_suffix}')

def main():
    parser = argparse.ArgumentParser('linode-dynamic-dns')
    parser.add_argument(
        '--version',
        action='version',
        version=__version__
    )
    parser.add_argument(
        '-s',
        type=int,
        dest='sleep',
        default=None,
        help='Run continuously and sleep the specified number of seconds'
    )
    args = parser.parse_args()

    logging.basicConfig(format='%(message)s', level=logging.INFO)

    domain = os.environ['DOMAIN']
    host = os.environ['HOST']
    token = os.environ['TOKEN']

    api = LinodeAPI(token)

    if args.sleep is not None:
        while True:
            update_dns(api, domain, host)
            time.sleep(args.sleep)
    else:
        update_dns(api, domain, host)


if __name__ == "__main__":
    main()
