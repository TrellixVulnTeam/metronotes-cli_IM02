#!/usr/bin/env python

import os, sys
import shutil
import ctypes.util
import configparser, platform
import urllib.request
import tarfile, zipfile
import appdirs
import hashlib
from decimal import Decimal as D

# generate commented config file from arguments list (client.CONFIG_ARGS and server.CONFIG_ARGS) and known values
def generate_config_file(filename, config_args, known_config={}, overwrite=False):
    if not overwrite and os.path.exists(filename):
        return

    config_dir = os.path.dirname(os.path.abspath(filename))
    if not os.path.exists(config_dir):
        os.makedirs(config_dir, mode=0o755)

    config_lines = []
    config_lines.append('[Default]')
    config_lines.append('')

    for arg in config_args:
        key = arg[0][-1].replace('--', '')
        value = None
        if key in known_config:
            value = known_config[key]
        elif 'default' in arg[1]:
            value = arg[1]['default']
        if value is None:
            key = '# {}'.format(key)
            value = ''
        elif isinstance(value, bool):
            value = '1' if value else '0'
        elif isinstance(value, (float, D)):
            value = format(value, '.8f')

        config_lines.append('# {}'.format(arg[1]['help']))
        config_lines.append('{} = {}'.format(key, value))
        config_lines.append('')

    with open(filename, 'w', encoding='utf8') as config_file:
        config_file.writelines("\n".join(config_lines))
    os.chmod(filename, 0o660)

def extract_old_config():
    old_config = {}

    old_appdir = appdirs.user_config_dir(appauthor='Metronotes', appname='metronotesd', roaming=True)
    old_configfile = os.path.join(old_appdir, 'metronotesd.conf')

    if os.path.exists(old_configfile):
        configfile = configparser.ConfigParser()
        configfile.read(old_configfile)
        if 'Default' in configfile:
            for key in configfile['Default']:
                new_key = key.replace('backend-rpc-', 'backend-')
                new_key = new_key.replace('blockchain-service-name', 'backend-name')
                new_value = configfile['Default'][key].replace('jmcorgan', 'addrindex')
                old_config[new_key] = new_value

    return old_config

def extract_bitcoincore_config():
    bitcoincore_config = {}

    # Figure out the path to the bitcoin.conf file
    if platform.system() == 'Darwin':
        btc_conf_file = os.path.expanduser('~/Library/Application Support/Bitcoin/')
    elif platform.system() == 'Windows':
        btc_conf_file = os.path.join(os.environ['APPDATA'], 'Bitcoin')
    else:
        btc_conf_file = os.path.expanduser('~/.bitcoin')
    btc_conf_file = os.path.join(btc_conf_file, 'bitcoin.conf')

    # Extract contents of bitcoin.conf to build service_url
    if os.path.exists(btc_conf_file):
        conf = {}
        with open(btc_conf_file, 'r') as fd:
            # Bitcoin Core accepts empty rpcuser, not specified in btc_conf_file
            for line in fd.readlines():
                if '#' in line or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                conf[k.strip()] = v.strip()

            config_keys = {
                'rpcport': 'backend-port',
                'rpcuser': 'backend-user',
                'rpcpassword': 'backend-password',
                'rpcssl': 'backend-ssl'
            }

            for bitcoind_key in config_keys:
                if bitcoind_key in conf:
                    metronotes_key = config_keys[bitcoind_key]
                    bitcoincore_config[metronotes_key] = conf[bitcoind_key]

    return bitcoincore_config

def get_server_known_config():
    server_known_config = {}

    bitcoincore_config = extract_bitcoincore_config()
    server_known_config.update(bitcoincore_config)

    old_config = extract_old_config()
    server_known_config.update(old_config)

    return server_known_config

# generate client config from server config
def server_to_client_config(server_config):
    client_config = {}

    config_keys = {
        'backend-connect': 'wallet-connect',
        'backend-port': 'wallet-port',
        'backend-user': 'wallet-user',
        'backend-password': 'wallet-password',
        'backend-ssl': 'wallet-ssl',
        'backend-ssl-verify': 'wallet-ssl-verify',
        'rpc-host': 'metronotes-rpc-connect',
        'rpc-port': 'metronotes-rpc-port',
        'rpc-user': 'metronotes-rpc-user',
        'rpc-password': 'metronotes-rpc-password'
    }

    for server_key in config_keys:
        if server_key in server_config:
            client_key = config_keys[server_key]
            client_config[client_key] = server_config[server_key]

    return client_config

def generate_config_files():
    from metronotescli.server import CONFIG_ARGS as SERVER_CONFIG_ARGS
    from metronotescli.client import CONFIG_ARGS as CLIENT_CONFIG_ARGS
    from metronoteslib.lib import config, util

    configdir = appdirs.user_config_dir(appauthor=config.XMN_NAME, appname=config.APP_NAME, roaming=True)

    server_configfile = os.path.join(configdir, 'server.conf')
    if not os.path.exists(server_configfile):
        # extract known configuration
        server_known_config = get_server_known_config()
        # generate random password
        if 'rpc-password' not in server_known_config:
            server_known_config['rpc-password'] = util.hexlify(util.dhash(os.urandom(16)))
        generate_config_file(server_configfile, SERVER_CONFIG_ARGS, server_known_config)

        client_configfile = os.path.join(configdir, 'client.conf')
        if not os.path.exists(client_configfile):
            client_known_config = server_to_client_config(server_known_config)
            generate_config_file(client_configfile, CLIENT_CONFIG_ARGS, client_known_config)

def zip_folder(folder_path, zip_path):
    zip_file = zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED)
    for root, dirs, files in os.walk(folder_path):
        for a_file in files:
            zip_file.write(os.path.join(root, a_file))
    zip_file.close()

def before_py2exe_build(win_dist_dir):
    # Clean previous build
    if os.path.exists(win_dist_dir):
        shutil.rmtree(win_dist_dir)
    # py2exe don't manages entry_points
    for exe_name in ['client', 'server']:
        shutil.copy('metronotescli/__init__.py', 'metronotes-{}.py'.format(exe_name))
        with open('metronotes-{}.py'.format(exe_name), 'a') as fp:
            fp.write('{}_main()'.format(exe_name))
    # Hack
    src = 'C:\\Python34\\Lib\\site-packages\\flask_httpauth.py'
    dst = 'C:\\Python34\\Lib\\site-packages\\flask\\ext\\httpauth.py'
    shutil.copy(src, dst)

def after_py2exe_build(win_dist_dir):
    # clean temporaries scripts
    for exe_name in ['client', 'server']:
        os.remove('metronotes-{}.py'.format(exe_name))
    # py2exe copies only pyc files in site-packages.zip
    # modules with no pyc files must be copied in 'dist/library/'
    import metronoteslib, certifi
    additionals_modules = [metronoteslib, certifi]
    for module in additionals_modules:
        moudle_file = os.path.dirname(module.__file__)
        dest_file = os.path.join(win_dist_dir, 'library', module.__name__)
        shutil.copytree(moudle_file, dest_file)
    # additionals DLLs
    dlls = ['ssleay32.dll', 'libssl32.dll', 'libeay32.dll']
    dlls.append(ctypes.util.find_msvcrt())
    dlls_path = dlls
    for dll in dlls:
        dll_path = ctypes.util.find_library(dll)
        shutil.copy(dll_path, win_dist_dir)

    # compress distribution folder
    zip_path = '{}.zip'.format(win_dist_dir)
    zip_folder(win_dist_dir, zip_path)

    # Open,close, read file and calculate MD5 on its contents 
    with open(zip_path, 'rb') as zip_file:
        data = zip_file.read()    
        md5 = hashlib.md5(data).hexdigest()

    # include MD5 in the zip name
    new_zip_path = '{}-{}.zip'.format(win_dist_dir, md5)
    os.rename(zip_path, new_zip_path)

    # clean build folder
    shutil.rmtree(win_dist_dir)

    # Clean Hack
    os.remove('C:\\Python34\\Lib\\site-packages\\flask\\ext\\httpauth.py')


# Download bootstrap database
def bootstrap(overwrite=True, ask_confirmation=False):
    from metronoteslib.lib import config

    bootstrap_url = 'https://s3.amazonaws.com/metronotes-bootstrap/metronotesd-db.latest.tar.gz'
    bootstrap_url_testnet = 'https://s3.amazonaws.com/metronotes-bootstrap/metronotesd-testnet-db.latest.tar.gz'

    data_dir = appdirs.user_data_dir(appauthor=config.XMN_NAME, appname=config.APP_NAME, roaming=True)
    database = os.path.join(data_dir, '{}.db'.format(config.APP_NAME))
    database_testnet = os.path.join(data_dir, '{}.testnet.db'.format(config.APP_NAME))

    if not os.path.exists(data_dir):
        os.makedirs(data_dir, mode=0o755)

    if not overwrite and os.path.exists(database):
        return

    if ask_confirmation:
        question = 'Would you like to bootstrap your local Metronotes database from `https://s3.amazonaws.com/metronotes-bootstrap/`? (y/N): '
        if input(question).lower() != 'y':
            return

    # Progress bar
    def reporthook(blocknum, blocksize, totalsize):
        readsofar = blocknum * blocksize
        if totalsize > 0:
            percent = readsofar * 1e2 / totalsize
            s = "\r%5.1f%% %*d / %d" % (
                percent, len(str(totalsize)), readsofar, totalsize)
            sys.stderr.write(s)
            if readsofar >= totalsize: # near the end
                sys.stderr.write("\n")
        else: # total size is unknown
            sys.stderr.write("read %d\n" % (readsofar,))

    print('Downloading mainnet database from {}…'.format(bootstrap_url))
    urllib.request.urlretrieve(bootstrap_url, 'metronotesd-db.latest.tar.gz', reporthook)
    print('Extracting…')
    with tarfile.open('metronotesd-db.latest.tar.gz', 'r:gz') as tar_file:
        def is_within_directory(directory, target):
            
            abs_directory = os.path.abspath(directory)
            abs_target = os.path.abspath(target)
        
            prefix = os.path.commonprefix([abs_directory, abs_target])
            
            return prefix == abs_directory
        
        def safe_extract(tar, path=".", members=None, *, numeric_owner=False):
        
            for member in tar.getmembers():
                member_path = os.path.join(path, member.name)
                if not is_within_directory(path, member_path):
                    raise Exception("Attempted Path Traversal in Tar File")
        
            tar.extractall(path, members, numeric_owner=numeric_owner) 
            
        
        safe_extract(tar_file)
    print('Copying {} to {}…'.format('metronotesd.9.db', database))
    shutil.move('metronotesd.9.db', database)
    os.chmod(database, 0o660)

    print('Downloading testnet database from {}…'.format(bootstrap_url_testnet))
    urllib.request.urlretrieve(bootstrap_url_testnet, 'metronotesd-testnet-db.latest.tar.gz', reporthook)
    print('Extracting…')
    with tarfile.open('metronotesd-testnet-db.latest.tar.gz', 'r:gz') as tar_file:
        def is_within_directory(directory, target):
            
            abs_directory = os.path.abspath(directory)
            abs_target = os.path.abspath(target)
        
            prefix = os.path.commonprefix([abs_directory, abs_target])
            
            return prefix == abs_directory
        
        def safe_extract(tar, path=".", members=None, *, numeric_owner=False):
        
            for member in tar.getmembers():
                member_path = os.path.join(path, member.name)
                if not is_within_directory(path, member_path):
                    raise Exception("Attempted Path Traversal in Tar File")
        
            tar.extractall(path, members, numeric_owner=numeric_owner) 
            
        
        safe_extract(tar_file)
    print('Copying {} to {}…'.format('metronotesd.9.testnet.db', database_testnet))
    shutil.move('metronotesd.9.testnet.db', database_testnet)
    os.chmod(database_testnet, 0o660)

    # Clean files
    os.remove('metronotesd-db.latest.tar.gz')
    os.remove('metronotesd-testnet-db.latest.tar.gz')
    os.remove('checksums.txt')
