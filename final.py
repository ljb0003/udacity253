#encoding:utf-8
import os
import random
import hmac
import string
import json
from datetime import datetime
import logging

import webapp2
import jinja2


from google.appengine.api import memcache
from google.appengine.ext import db

template_dir = os.path.join(os.path.dirname(__file__), 'templates')
jinja_env = jinja2.Environment(loader = jinja2.FileSystemLoader(template_dir),
        autoescape = True)

class Article(db.Model):
    subject = db.StringProperty(required = True)
    content = db.TextProperty(required = True)
    created = db.DateTimeProperty(auto_now_add = True)

    def json(self):
        return {'subject':self.subject, 'content':self.content,
            'created':self.created.strftime('%H:%M:%S %d-%m-%Y')}


    @classmethod
    def query(self, id, update=False):
        key = 'article%d' % id
        val = memcache.get(key)
        if update or not val:
            val = (super(Article, self).get_by_id(int(id)), datetime.now())
            memcache.set(key, val)

        return val

class Wiki(db.Model):
    url = db.StringProperty(required=True)
    content = db.TextProperty(required=True)
    created = db.DateTimeProperty(auto_now_add=True)

class User(db.Model):
    username = db.StringProperty(required=True)
    password = db.StringProperty(required=True)
    email = db.StringProperty(required=False)

def hash_password(password, salt=None):
    if salt is None:
        salt = ''.join([random.choice(string.letters) for _ in xrange(6)])
    salt = str(salt)
    return '%s|%s' % (hmac.new(salt, password).hexdigest(), salt)

def make_uid_cookie(uid, hash_pwd, salt=None):
    if salt is None:
        salt = ''.join([random.choice(string.letters) for _ in xrange(6)])
    salt = str(salt)
    return '%s|%s|%s' % (uid, hmac.new(salt, str(uid)+hash_pwd).hexdigest(), salt)

class BaseHandler(webapp2.RequestHandler):
    def render_str(self, template, **params):
        t = jinja_env.get_template(template)
        return t.render(params)

    def render(self, template, **kw):
        self.response.out.write(self.render_str(template, **kw))

    def write(self, *a, **kw):
        self.response.out.write(*a, **kw)

    def initialize(self, request, response):
        uid_str = request.cookies.get('user_id')
        self.user = self.check_uid(uid_str)
        return super(BaseHandler, self).initialize(request, response)

    def check_uid(self, uid_str):
        if not uid_str:
            return False
        strs = uid_str.split('|')
        if len(strs) != 3:
            return False
        uid, hmac, salt = strs
        user = User.get_by_id(int(uid))
        if not user:
            return False
        if make_uid_cookie(uid, user.password, salt) == uid_str:
            return user


def top_articles(update=False):
    key = 'top'
    val = memcache.get(key)
    if update or not val:
        val = (db.GqlQuery("select * from Article order by created desc limit 10"), datetime.now())
        memcache.set(key, val)

    return val

class MainPage(BaseHandler):
    def get(self):
        articles, query_time = top_articles()
        self.render("blog-front.html", articles=articles, query_time=(datetime.now()-query_time).seconds)

class MainPageJson(BaseHandler):
    def get(self):
        articles, _ = top_articles()
        self.response.headers.add_header('Content-Type', 
                'application/json; charset=utf-8')
        self.write(json.dumps([a.json() for a in articles], ensure_ascii=False))

class NewPage(BaseHandler):
    def render_front(self, subject="", content="", error=""):
        self.render("newpost.html", subject=subject, content=content, error=error)

    def get(self):
        self.render_front()
    
    def post(self):
        subject = self.request.get("subject")
        content = self.request.get('content')
        if subject and content:
            a = Article(subject = subject, content = content)
            a.put()
            
            top_articles(update=True)

            self.redirect("/final/%d" % a.key().id())
        else:
            error = "We need both a subject and some content!"
            self.render_front(subject=subject, content=content, error=error)

class ArticlePage(BaseHandler):
    def get(self, article_id):
        article, query_time = Article.query(int(article_id))
        self.render("article.html", article=article, query_time=(datetime.now()-query_time).seconds)

class ArticlePageJson(BaseHandler):
    def get(self, article_id):
        article, _ = Article.query(int(article_id))
        self.response.headers.add_header('Content-Type', 
                'application/json; charset=utf-8')
        self.write(json.dumps(article.json(), ensure_ascii=False))
 
class Signup(BaseHandler):
    def get(self):
        self.render('signup.html')

    def post(self):
        username = self.request.get('username')
        password = self.request.get('password')
        verify = self.request.get('verify')
        email = self.request.get('email')

        if not username:
            self.render('signup.html', username_error='Username is required.',
                    username=username, email=email)
            return
        if not password:
            self.render('signup.html', password_error='Password is required.',
                    username=username, email=email)
            return
        if password != verify:
            self.render('signup.html', verify_error='Your passwords do not'
                    ' match', username=username, email=email)
            return

        if db.GqlQuery('select * from User where username=:username',
                username=username).get():
            self.render('signup.html', username_error='The user already'
                    ' exists.', username=username, email=email)
            return
        user = User(username=username, password=hash_password(password), email=email)
        user.put()

        uid_str = make_uid_cookie(user.key().id(), user.password)
        self.response.headers.add_header('Set-Cookie', 'user_id=%s; path=/' % uid_str)
        self.redirect('/final/welcome')
        

class Welcome(BaseHandler):
    def get(self):
        uid_str = self.request.cookies.get('user_id')
        user = self.check_uid(uid_str)
        if not user:
            self.redirect('/final/signup')
            return
 
        self.write('Welcome, ' + user.username)

class Login(BaseHandler):
    def get(self):
        self.render('login.html')

    def post(self):
        username = self.request.get('username')
        password = self.request.get('password')
        if not username:
            self.render('signup.html', username_error='Username is required.',
                    username=username)
            return
        if not password:
            self.render('signup.html', password_error='Password is required.',
                    username=username)
            return

        user = db.GqlQuery('select * from User where username=:username',
                username=username).get()
        if not user:
            self.render('signup.html', username_error='The user does not'
                    ' exists.', username=username)
            return
        hash_pwd, salt = user.password.split('|')
        if hash_password(password, salt) != user.password:
            self.render('signup.html', password_error='Password is incorrect.')
            return

        uid_str = make_uid_cookie(user.key().id(), user.password)
        self.response.headers.add_header('Set-Cookie', 'user_id=%s; Path=/' % uid_str)
        self.redirect('/final/welcome')

class Logout(BaseHandler):
    def get(self):
        self.response.headers.add_header('Set-Cookie', 'user_id=; Path=/')
        self.redirect('/final/signup')

class Flush(BaseHandler):
    def get(self):
        memcache.flush_all()
        self.redirect('/final/')

class WikiPage(BaseHandler):
    def get(self, url):
        id = self.request.get('id')
        if id:
            wiki = Wiki.get_by_id(int(id))
            self.render('wikipage.html', content=wiki.content)
            return

        content = memcache.get(url)
        if content:
            self.render('wikipage.html', content=content)
            return
        wiki = db.GqlQuery('select * from Wiki where url=:url order by created desc limit 1', url=url).get()
        if not wiki:
            self.redirect('/final/_edit' + url)
            return
        memcache.set(url, wiki.content)
        self.render('wikipage.html', content=wiki.content)

class EditPage(BaseHandler):
    def get(self, url):
        if not self.user:
            self.redirect('/final/signup')
            return

        id = self.request.get('id')
        if id:
            wiki = Wiki.get_by_id(int(id))
        else:
            wiki = db.GqlQuery('select * from Wiki where url=:url', url=url).get()
        content = wiki.content if wiki else ''
        self.render('wikiform.html', content=content)

    def post(self, url):
        if not self.user:
            self.redirect('/final/signup')
            return
        content = self.request.get('content')
        wiki = Wiki(url=url, content=content)
        wiki.put()
        memcache.set(url, content)
        self.redirect('/final' + url)

class HistoryPage(BaseHandler):
    def get(self, url):
        wikis = db.GqlQuery('select * from Wiki where url=:url', url=url)
        self.render('history.html', wikis=wikis)

PAGE_RE = r'(/(?:[a-zA-Z0-9_-]+/?)*)'
app = webapp2.WSGIApplication([
    ('/final/signup', Signup),
    ('/final/welcome', Welcome),
    ('/final/login', Login),
    ('/final/logout', Logout),
    (r'/final/?', MainPage),
    (r'/final/\.json', MainPageJson), 
    (r'/final/newpost', NewPage),
    (r'/final/(\d+)', ArticlePage),
    (r'/final/(\d+)\.json', ArticlePageJson),
    (r'/final/flush', Flush),
    ('/final/_edit' + PAGE_RE, EditPage),
    ('/final/_history' + PAGE_RE, HistoryPage),
    ('/final' + PAGE_RE, WikiPage),
    ],
    debug=True)
