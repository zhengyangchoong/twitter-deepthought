import os
import time
import datetime
import json
import twitter
import bz2
import threading
import logging
import pprint
import shutil
import sys
import helpers
from config import ck, cs, ot, ots, public_dir

module_logger = logging.getLogger(__name__)


def init_twitter_api():
    """ Initializes a Twitter API object """
    module_logger.debug("Initializing Twitter API")
    # Authenticate with twitter api
    auth = twitter.oauth.OAuth(ot, ots, ck, cs)
    twitter_api = twitter.Twitter(auth=auth)
    return twitter_api


class Crawler(object):
    """ Accepts Twitter tweet stream and save them hourly

    Attributes:
        total_tweets        The total number of tweets the crawler has collected
        tps                 Tweets Per Second
        start_time          Time when the crawler started
        stream              The Twitter stream where the crawler will get the tweets from
        dir                 The current directory where the crawler is writing to
        tweets_file         The current file where tweets are being stored
        tps_file            The current file where Tweets Per Second are being recorded
        queue               The shared queue with the Spike thread for analysing files
    """

    total_tweets = 0
    tps = 0
    start_time = datetime.time()
    stream = twitter.TwitterStream()
    dir = ""
    tweets_file = None
    tps_file = None
    queue = None

    def __init__(self):
        """ Initializes class attributes
        """
        # Initialize logging
        self.logger = logging.getLogger(__name__)

        # Initializes a Twitter Stream
        twitter_api = init_twitter_api()
        self.logger.debug("Initializing Twitter Stream")
        self.stream = twitter.TwitterStream(auth=twitter_api.auth) \
            .statuses.sample(language='en')

        # Initializes the directory the crawler is going to write to
        self.init_dir()

    def start(self, queue):
        """
        Main function to start the collection of tweets
        :param queue: Shared queue between Crawler thread and Spike thread of files to be analysed
        """
        self.logger.info("Started crawling")

        # Initialize shared queue
        self.queue = queue

        # Mark start time
        self.start_time = datetime.datetime.now()

        # Initial call to update status
        self.update_status()

        # Iterate tweets
        try:
            for tweet in self.stream:
                # Update counters
                self.total_tweets += 1
                self.tps += 1

                # Write tweet to file
                timestamp = str(time.time())
                self.tweets_file.write('"' + timestamp + '":' + json.dumps(tweet) + ',')

                # If the current directory name is outdated
                if self.dir != time.strftime('%d-%m-%Y_%H'):
                    self.change_dir()
        except:
            self.logger.error("Tweet stream stopped unexpectedly")

    def __del__(self):
        """ Do cleanup work
        """
        self.logger.warn('Crawling stopped/interrupted')
        self.tweets_file.close()
        self.tps_file.close()

    def update_status(self):
        """ Log the current status of the crawler and sends status to frontend
        """
        if threading is None:
            return

        # Update status every second
        t = threading.Timer(1, self.update_status)
        t.start()
        t.name = "Crawler status thread"

        # Calculate time elapsed
        elapsed_time = datetime.datetime.now() - self.start_time

        status = {
            'duration': int(elapsed_time.total_seconds()),
            'total_tweets': self.total_tweets,
            'tps': self.tps,
            'dir': self.dir,
            'tweets_file_size': os.path.getsize(self.tweets_file.name),
        }

        # Logs to console
        # self.logger.debug("\n" + pprint.pformat(status) + "\n")

        # Update status to front end
        with open(public_dir + "status.json", 'w') as f:
            f.write(json.dumps(status))

        # Update tps file
        timestamp = str(time.time())
        self.tps_file.write("\"" + timestamp + "\":" + str(self.tps) + ',')

        # Reset counter for tweets per second
        self.tps = 0

    def change_dir(self):
        """ Change the dir the crawler is writing to
            and starts processing previous hour's dir
        """
        if self.dir != time.strftime('%d-%m-%Y_%H'):
            self.logger.info("Changing dir from " + self.dir + " to " + time.strftime('%d-%m-%Y_%H'))

            # Close the old files to allow processing
            self.tweets_file.close()
            self.tps_file.close()

            # Make a callback function to add the uploaded dir to the shared Queue
            callback = lambda f: self.queue.put(f)

            # Starts the upload and processing
            t = threading.Thread(target=self.process_dir, args=(self.dir, callback))
            t.start()
            t.name = "Crawler upload thread"

            # Change dir
            self.init_dir()

    def init_dir(self):
        """ Initializes the directory the crawler is going to write to
        """
        self.logger.debug("Initializing dir")
        self.dir = time.strftime('%d-%m-%Y_%H')
        if not os.path.exists(self.dir):
            os.makedirs(self.dir)

        self.tweets_file = open(self.dir + '/tweets.json', 'ab', 0)
        self.tps_file = open(self.dir + '/tps.json', 'ab', 0)

    @staticmethod
    def process_dir(dir, callback=None):
        """
        Given a dir, compress and process all its files,
        and then upload and delete it
        :param dir: The name of dir to process
        :param callback: Optional callback function
        """
        module_logger.info("Processing dir " + dir)
        # Loop through each file in the directory
        for root, dirs, files in os.walk(dir):
            for name in files:
                # Get the file path of current file
                file_path = os.path.join(root, name)

                # Open the original file and the compressed file
                original_f = open(file_path)
                compressed_f = bz2.BZ2File(file_path + '.bz2', 'w')

                # If the current file is a JSON file, we have to format it
                # First, we prepend a '{'
                if ".json" in name:
                    compressed_f.write("{")

                # Read the original file chunk by chunk, due to memory limitations
                # Chunk size is set to 1MB
                chunk_size = 1024*1024
                for chunk in helpers.read_file_in_chunks(original_f, chunk_size):
                    # If this is a JSON file and the current chunk is the last chunk in the file,
                    # we remove the trailing comma from the original file
                    # We can tell if this is the last chunk as the chunk size will be smaller than what we asked for
                    if ".json" in name and sys.getsizeof(chunk) < chunk_size:
                        compressed_f.write(chunk[:-1])
                    else:
                        compressed_f.write(chunk)

                # Lastly, we prepend a '}'
                if ".json" in name:
                    compressed_f.write("}")

                # Close both files
                original_f.close()
                compressed_f.close()

                # Remove the old, uncompressed file
                os.remove(file_path)

        # Upload the directory
        key_name = dir + '.zip'
        helpers.upload_dir(dir, key_name)

        # Delete the directory after upload, to save space
        shutil.rmtree(dir)

        # If callback is set and is indeed a function, call it with param of the key used
        if callback is not None and callable(callback):
            callback(key_name)