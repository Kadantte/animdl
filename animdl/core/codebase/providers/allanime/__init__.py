import json
from collections import defaultdict
from functools import partial

import regex
import yarl

from ....config import ALLANIME
from ...helper import construct_site_based_regex

REGEX = construct_site_based_regex(ALLANIME, extra_regex=r'/anime/([^?&/]+)')

SOURCE_URLS = regex.compile(r'sourceUrl[:=]"(.+?)"')
EPISODES_REGEX = regex.compile(r'\\"availableEpisodesDetail\\":({.+?})')

SANITIZER = {
    '\\u002F': '/',
}

EMBED_BLACKLIST = (
    regex.compile("streaming\.php\?"),
    "https://mp4upload.com/",
    "https://streamsb.net/",
    "https://dood.to/",
    "https://videobin.co/",
    "https://ok.ru",
    "https://streamlare.com",
) 

def is_blacklisted(url):
    for blacklist in EMBED_BLACKLIST:
        if isinstance(blacklist, regex.Pattern):
            if blacklist.search(url):
                return True
            continue

        if blacklist in url:
            return True
    return False

def iter_episodes(episode_dictionary, anime_page_url):
    episodes = defaultdict(list)
    
    for type_of, episode_numbers in episode_dictionary.items():
        for episode in episode_numbers:
            episodes[int(episode) if episode.isdigit() else 0].append(("Episode {} [{}]".format(episode, type_of.upper()), anime_page_url + "/episodes/{}/{}".format(type_of, episode)))
        
    yield from sorted(episodes.items(), key=lambda x: x[0])

def sanitize(content):
    for key, item in SANITIZER.items():
        content = content.replace(key, item)
    return content


def extract_content(session, content, *, api_endpoint):
    for title, url in content:
        for source_urls in SOURCE_URLS.finditer(session.get(url).text):
            content_uri = yarl.URL(sanitize(source_urls.group(1)))

            if not content_uri.host:
                link_content = api_endpoint.join(content_uri.with_name(content_uri.name + ".json").with_query(content_uri.query)).human_repr()
                response = session.get(link_content)

                if response.status_code >= 400:
                    continue

                json_response = response.json()
                
                if not isinstance(json_response, list):
                    json_response = json_response.get('links')
                
                for link in json_response:
                    stream_uri = yarl.URL(link.get('link'))
                    uri_ref = (stream_uri if stream_uri.host else api_endpoint.join(stream_uri)).human_repr()
                    yield {'stream_url': uri_ref, 'title': title, 'headers': {'referer': (api_endpoint.with_path('player').with_query({'url': uri_ref})).human_repr()}}
            else:
                to_direct = content_uri.human_repr()
                if not is_blacklisted(to_direct):
                    yield {'stream_url': to_direct, 'title': title}


def fetcher(session, url, check):
    animepage_url = (ALLANIME + "anime/{}").format(REGEX.search(url).group(1))

    api_endpoint = yarl.URL(session.get(ALLANIME + "getVersion").json().get('episodeIframeHead', ''))

    for episode, content in iter_episodes(json.loads(EPISODES_REGEX.search(session.get(animepage_url).text).group(1).replace('\\"', '"')), animepage_url):
        if check(episode):
            yield partial(lambda s, c: list(extract_content(s, c, api_endpoint=api_endpoint)), session, content), episode
