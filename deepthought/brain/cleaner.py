from nltk.corpus import stopwords
import os
import json
import re
import base64
from config import boto_access, boto_secret
from boto.s3.connection import Location, S3Connection
from boto.s3.key import Key
import gzip
import zipfile
import logging
stop = stopwords.words('english')

class launch(object):
	def __init__(self, key, queue):
		logging.basicConfig(format='%(asctime)s : %(levelname)s : %(message)s', level=logging.INFO) 
		logging.basicConfig(format='%(asctime)s : %(levelname)s : %(message)s', level=logging.WARNING)  
		self.conn = S3Connection(boto_access, boto_secret)
		self.bucket = self.conn.get_bucket('twitter-deepthought')
		self.k = Key(self.bucket)
		self.z = False
		if not any([key == z.name for z in self.bucket.list()]):
			key = key + '.zip'
			logging.warning("Using the newer zipped file. Meows.")
			self.z = True
		self.key = key
		self.k.key = key
		logging.info("[{}] Initialising brain.cleaner.launch()...".format(self.key))
		logging.info("[{}] This module loads and cleans a compressed file.".format(self.key))
		
		self.dirs = {
		'dump':os.path.join('thinking/braindump', self.key),
		}
		self.f_text = open(self.dirs['dump'], 'w')
		self.t_stop = ['rt', '#','http', '@']		
		queue.put(True)
	def load(self):
		if not os.path.exists(os.path.join('thinking', self.key)):
			print ("[{}] Compressed file does not exist. Downloading...").format(self.key)
			if self.z:
				self.k.get_contents_to_filename(os.path.join('thinking',self.key + '.zip'))
			else:
				self.k.get_contents_to_filename(os.path.join('thinking',self.key))
		else:
			print 'File already exists. Skipping.'
		if self.z:
			zf = zipfile.ZipFile(os.path.join('thinking',self.key + '.zip'))
			zf.extractall()
		else:
			self.f = gzip.open(os.path.join('thinking',self.key), 'rb')
		print "Downloaded " + self.key

	def sweep(self):
		print "Attempting to clean " + self.key
		for tweet in self.f:
			tweet = json.loads(tweet)
			text = tweet['text']
			text = self.clean(text)
			self.f_text.write(' '.join(text).encode('ascii','ignore') + '\n')
		self.f_text.close()
		print "Dump file for cleaned text created at " + self.dirs['dump']

	def clean(self,text):
		tl = unicode(text.lower()).split(' ')
		tl = self.strip_emojis(tl)
		tl = filter(lambda w: (not w in stop), tl)
		tl = map(self.strip_escape, tl)
		tl = filter(self.strip_others, tl)
		return tl

	def strip_emojis(self, tl):
		myre = re.compile(u'['u'\U0001f300-\U0001ffff'u'\U0001f600-\U0001f64f'u'\U0001f680-\U0001f6ff'u'\u2600-\u26ff\u2700-\u27bf]+', re.UNICODE)
		return myre.sub('', ' '.join(tl)).split(' ')

	def strip_escape(self,text):
		while True:
			if text[:1] == '\n':
				text = text[1:]
			else:
				break
		return text

	def strip_others(self, text):
		for a in self.t_stop:
			if a in text:
				return False
		return True