import os, sys, json

from urllib import urlencode
from tarfile import TarFile
from gzip import GzipFile
from StringIO import StringIO
from uuid import uuid4
from time import sleep
from tempfile import mkdtemp
from os.path import commonprefix, join, isdir, exists, basename
from shutil import make_archive, rmtree

from flask import Flask, request, redirect, render_template, jsonify, send_file, make_response
from requests import get, post, Session
from flask.ext.heroku import Heroku
import oauth2

heroku_authorize_url = 'https://id.heroku.com/oauth/authorize'
heroku_access_token_url = 'https://id.heroku.com/oauth/token'

class SetupError (Exception):
    pass

app = Flask(__name__)
heroku = Heroku(app)

@app.route("/")
def index():
    ''' Render front page with all the info.
    
        If not running locally, force SSL.
    '''
    return render_template('index.html', style_base=get_style_base(request))


@app.route('/prepare-app', methods=['POST'])
def prepare_app():
    ''' Prepare app, ask Heroku to authenticate, return to /callback-heroku.
    '''
    application_url = "http://0.0.0.0:5000"
    scribd_api_key = "not supplied"
    scribd_api_secret = "not supplied"
    host_url = "not supplied"
    mail_username = "not supplied"
    mail_password = "not supplied"
    sqlalchemy_database_uri = "not supplied"
    akismet_key = "not supplied"
    list_of_admins = "not supplied"
    recaptcha_public_key = "not supplied"
    recaptcha_private_key = "not supplied"
    agency_name = "City of X"
    default_owner_email = "richa@codeforamerica.org"
    default_owner_reason = "a reason"
    google_feedback_form_id = "not supplied"
    liaisons_url = "not supplied"
    staff_url = "not supplied"
    logo_on_white_url = "not supplied"
    logo_on_black_url = "not supplied"
    default_mail_sender = "not supplied"


    env = dict(ENVIRONMENT = 'PRODUCTION', APPLICATION_URL = application_url, SCRIBD_API_KEY = scribd_api_key, SCRIBD_API_SECRET = scribd_api_secret, HOST_URL = host_url, MAIL_USERNAME = mail_username, MAIL_PASSWORD = mail_password, DEFAULT_MAIL_SENDER = default_mail_sender, SECRET_KEY = '123456789setthistorandomnumer', SQLALCHEMY_DATABASE_URI = 'postgresql://localhost/recordtrac', AKISMET_KEY = akismet_key, LIST_OF_ADMINS = list_of_admins, RECAPTCHA_PUBLIC_KEY = recaptcha_public_key, RECAPTCHA_PRIVATE_KEY = recaptcha_private_key, AGENCY_NAME = agency_name, DEFAULT_OWNER_EMAIL = default_owner_email, DEFAULT_OWNER_REASON = default_owner_reason, GOOGLE_FEEDBACK_FORM_ID = google_feedback_form_id, LIAISONS_URL = liaisons_url, STAFF_URL = staff_url, LOGO_ON_WHITE_URL = logo_on_white_url, LOGO_ON_BLACK_URL = logo_on_black_url )


    tarpath = prepare_tarball('http://github.com/codeforamerica/recordtrac/tarball/master/',
                              dict(name='RecordTrac', env=env))
    
    client_id, _, redirect_uri = heroku_client_info(request)
    
    query_string = urlencode(dict(client_id=client_id, redirect_uri=redirect_uri,
                                  response_type='code', scope='global',
                                  state=tarpath, expires_in = 2592000, description = "RecordTrac setup"))
    
    return redirect(heroku_authorize_url + '?' + query_string)

    resp = post('https://api.heroku.com/oauth/authorizations', data=query_string)
    return callback_heroku(resp)


@app.route('/tarball/<path:filename>')
def get_tarball(filename):
    ''' Return the named application tarball from the temp directory.
    '''
    filepath = join(os.environ.get('TMPDIR', '/tmp'), filename)
    
    return send_file(filepath)


def callback_heroku(callback):
    ''' Complete Heroku authentication, start app-setup, redirect to app page.
    '''
    resp = json.loads(callback.content)
    access_token = resp['id']
    grant = dict(code = access_token, type = 'authorization_code')
    client = dict(secret = access_token)
    refresh_token = dict(token = access_token)
    data = dict(grant_type = 'authorization_code', client_secret = access_token, grant = grant, client = client,
                refresh_token = refresh_token, code = access_token)
    
    resp = post('https://api.heroku.com/oauth/tokens', data=data)
    access = json.loads(resp.content)
    access_token, token_type = access['access_token'], access['token_type']

    try:
        tar = basename('http://github.com/codeforamerica/recordtrac/tarball/master/')
        url = 'https://{0}/tarball/{1}?token={2}'.format(request.host, tar, access_token)
        app_name = create_app(access_token, url)

        return redirect('https://dashboard.heroku.com/apps/{0}/activity'.format(app_name))
    
    finally:
        os.remove(tarpath)

def get_scheme(request):
    ''' Get the current URL scheme, e.g. 'http' or 'https'.
    '''
    if 'x-forwarded-proto' in request.headers:
        return request.headers['x-forwarded-proto']
    
    return request.scheme

def get_style_base(request):
    ''' Get the correct style base URL for the current scheme.
    '''
    if get_scheme(request) == 'https':
        return 'https://style.s.codeforamerica.org'
    
    return 'http://style.codeforamerica.org'


def heroku_client_info(request):
    ''' Return Client ID, secret, and redirect URI for Heroku OAuth use.
    '''
    scheme, host = get_scheme(request), request.host
    
    # Should be in config:
    if host == '127.0.0.1:5000':
        return "e46e254a-d99e-47c1-83bd-f9bc9854d467", "8cfd15f1-89b6-4516-9650-ce6650c78b4c", '{0}://{1}/callback-heroku'.format(scheme, host)
    else:
        return "830d0bcb-93b1-4520-aff5-6d09c67ef39a", "df960f36-7114-42fc-ae44-4d30a55e0a44", '{0}://{1}/callback-heroku'.format(scheme, host)

def prepare_tarball(url, app):
    ''' Prepare a tarball with app.json from the source URL.
    '''
    got = get(url, allow_redirects=True)
    raw = GzipFile(fileobj=StringIO(got.content))
    tar = TarFile(fileobj=raw)
    
    try:
        dirpath = mkdtemp(prefix='recordtrac-')
        rootdir = join(dirpath, commonprefix(tar.getnames()))
        tar.extractall(dirpath)
        
        if not isdir(rootdir):
            raise Exception('"{0}" is not a directory'.format(rootdir))

        with open(join(rootdir, 'app.json'), 'w') as out:
            json.dump(app, out)
        
        tarpath = make_archive(dirpath, 'gztar', rootdir, '.')
        
    finally:
        rmtree(dirpath)
    
    return tarpath

def create_app(access_token, source_url):
    ''' Create a Heroku application based on a tarball URL, return its name.
    '''
    client = Session()
    client.trust_env = False # https://github.com/kennethreitz/requests/issues/2066
    
    recordtrac_url = "http://github.com/codeforamerica/recordtrac/tarball/add-heroku-app-json-file\\"

    data = json.dumps({'source_blob': {'url': recordtrac_url}})

    headers = {'Content-Type': 'application/json',
               'Authorization': 'Bearer {0}'.format(access_token),
               'Accept': 'application/vnd.heroku+json; version=3'}

    posted = client.post('https://api.heroku.com/app-setups', headers=headers, data=data)
    setup_id = posted.json()['id']
    app_name = posted.json()['app']['name']

    while True:
        sleep(1)
        gotten = client.get('https://api.heroku.com/app-setups/{0}'.format(setup_id), headers=headers)
        setup = gotten.json()
    
        if setup['status'] == 'failed':
            raise Exception('Heroku failed to build from {0}, saying "{1}"'.format(source_url, setup['failure_message']))

        if setup['build']['id'] is not None:
            break

    return app_name

if __name__ == '__main__':
    app.run(port=5000, debug=True)
