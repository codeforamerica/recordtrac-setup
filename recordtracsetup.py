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

heroku_app_setup_url = 'https://api.heroku.com/app-setups'
heroku_app_setups_template = 'https://api.heroku.com/app-setups/{0}'
heroku_app_activity_template = 'https://dashboard.heroku.com/apps/{0}/activity'

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
    ns = 'not supplied'
    
    env = dict(
        # required form fields
        AGENCY_NAME = request.form.get('AGENCY_NAME', ns),
        DEFAULT_OWNER_EMAIL = request.form.get('DEFAULT_OWNER_EMAIL', ns),
        DEFAULT_OWNER_REASON = request.form.get('DEFAULT_OWNER_REASON', ns),

        # hidden form fields
        ENVIRONMENT = request.form.get('ENVIRONMENT', ns),
        DAYS_TO_FULFILL = request.form.get('DAYS_TO_FULFILL', ns),
        DAYS_AFTER_EXTENSION = request.form.get('DAYS_AFTER_EXTENSION', ns),
        DAYS_UNTIL_OVERDUE = request.form.get('DAYS_UNTIL_OVERDUE', ns),
        TIMEZONE = request.form.get('TIMEZONE', ns),
        SECRET_KEY = request.form.get('SECRET_KEY', ns),

        # missing form fields
        APPLICATION_URL = request.form.get('APPLICATION_URL', "http://0.0.0.0:5000"),
        SCRIBD_API_KEY = request.form.get('SCRIBD_API_KEY', ns),
        SCRIBD_API_SECRET = request.form.get('SCRIBD_API_SECRET', ns),
        HOST_URL = request.form.get('HOST_URL', ns),
        MAIL_USERNAME = request.form.get('MAIL_USERNAME', ns),
        MAIL_PASSWORD = request.form.get('MAIL_PASSWORD', ns),
        DEFAULT_MAIL_SENDER = request.form.get('DEFAULT_MAIL_SENDER', ns),
        SQLALCHEMY_DATABASE_URI = request.form.get('SQLALCHEMY_DATABASE_URI', 'postgresql://localhost/recordtrac'),
        AKISMET_KEY = request.form.get('AKISMET_KEY', ns),
        LIST_OF_ADMINS = request.form.get('LIST_OF_ADMINS', ns),
        RECAPTCHA_PUBLIC_KEY = request.form.get('RECAPTCHA_PUBLIC_KEY', ns),
        RECAPTCHA_PRIVATE_KEY = request.form.get('RECAPTCHA_PRIVATE_KEY', ns),
        GOOGLE_FEEDBACK_FORM_ID = request.form.get('GOOGLE_FEEDBACK_FORM_ID', ns),
        LIAISONS_URL = request.form.get('LIAISONS_URL', ns),
        STAFF_URL = request.form.get('STAFF_URL', ns),
        LOGO_ON_WHITE_URL = request.form.get('LOGO_ON_WHITE_URL', ns),
        LOGO_ON_BLACK_URL = request.form.get('LOGO_ON_BLACK_URL', ns)
        )
    
    tarpath = prepare_tarball('http://github.com/codeforamerica/recordtrac/tarball/master/',
                              dict(name='RecordTrac', env=env))
    
    client_id, _, redirect_uri = heroku_client_info(request)
    
    query_string = urlencode(dict(client_id=client_id, redirect_uri=redirect_uri,
                                  response_type='code', scope='global',
                                  state=tarpath, expires_in = 2592000, description = "RecordTrac setup"))
    
    return redirect(heroku_authorize_url + '?' + query_string)

@app.route('/tarball/<path:filename>')
def get_tarball(filename):
    ''' Return the named application tarball from the temp directory.
    '''
    filepath = join(os.environ.get('TMPDIR', '/tmp'), filename)
    
    return send_file(filepath)

@app.route('/callback-heroku')
def callback_heroku():
    ''' Complete Heroku authentication, start app-setup, redirect to app page.
    '''
    code, tar_id = request.args.get('code'), request.args.get('state')
    client_id, client_secret, redirect_uri = heroku_client_info(request)

    try:
        data = dict(grant_type='authorization_code', code=code,
                    client_secret=client_secret, redirect_uri='')
    
        response = post(heroku_access_token_url, data=data)
        access = response.json()
    
        if response.status_code != 200:
            if 'message' in access:
                raise SetupError('Heroku says "{0}"'.format(access['message']))
            else:
                raise SetupError('Heroku Error')
    
        url = '{0}://{1}/tarball/{2}'.format(get_scheme(request), request.host, tar_id)
        app_name = create_app(access['access_token'], url)
        
        return redirect(heroku_app_activity_template.format(app_name))
    
    except SetupError, e:
        values = dict(style_base=get_style_base(request), message=e.message)
        return make_response(render_template('error.html', **values), 400)

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
    if host == 'localhost:5000':
        return "e46e254a-d99e-47c1-83bd-f9bc9854d467", "8cfd15f1-89b6-4516-9650-ce6650c78b4c", '{0}://{1}/callback-heroku'.format(scheme, host)
    elif host == 'recordtrac-setup.herokuapp.com':
        return "830d0bcb-93b1-4520-aff5-6d09c67ef39a", "df960f36-7114-42fc-ae44-4d30a55e0a44", '{0}://{1}/callback-heroku'.format(scheme, host)
    else:
        raise NotImplementedError(host)

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

    posted = client.post(heroku_app_setup_url, headers=headers, data=data)
    setup_id = posted.json()['id']
    app_name = posted.json()['app']['name']

    while True:
        sleep(1)
        gotten = client.get(heroku_app_setups_template.format(setup_id), headers=headers)
        setup = gotten.json()
    
        if setup['status'] == 'failed':
            raise Exception('Heroku failed to build from {0}, saying "{1}"'.format(source_url, setup['failure_message']))

        if setup['build']['id'] is not None:
            break

    return app_name

if __name__ == '__main__':
    app.run(port=5000, debug=True)
