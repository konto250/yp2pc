"""発行済み購読URLと、プレイリスト・音質の永続的な対応表。"""
import json
import re
import secrets
import time
from yp2pc import storage
from yp2pc.core import AppError, playlist_id

TOKEN = re.compile(r'[a-f0-9]{32}\Z')


def read():
    path = storage.root() / 'subscriptions.json'
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


def issue(identifier, variant):
    identifier = playlist_id(identifier)
    if variant not in ('normal', 'am'):
        raise AppError('音質を正しく指定してください。')
    with storage.feed_operation:
        if not storage.registered(identifier):
            raise AppError('フィードが見つかりません。', 404, 'not_found')
        records = read()
        token = secrets.token_hex(16)
        while token in records:
            token = secrets.token_hex(16)
        records[token] = {'id': identifier, 'variant': variant, 'created': time.time()}
        storage.write_json(storage.root() / 'subscriptions.json', records)
        return token


def resolve(token):
    if not TOKEN.fullmatch(token):
        raise AppError('購読URLが見つかりません。', 404, 'not_found')
    record = read().get(token)
    if not record or not storage.registered(record['id']):
        raise AppError('購読URLが見つかりません。', 404, 'not_found')
    return record


def remove(identifier):
    with storage.feed_operation:
        records = read()
        remaining = {key: value for key, value in records.items() if value['id'] != identifier}
        if remaining != records:
            storage.write_json(storage.root() / 'subscriptions.json', remaining)


def urls(identifier, origin):
    with storage.feed_operation:
        history = [{'url': origin + '/subscribe/' + token + '.xml', **record}
                   for token, record in read().items() if record['id'] == identifier]
    history.sort(key=lambda record: record['created'], reverse=True)
    result = {'feedUrl': origin + '/feed/' + identifier + '.xml',
              'amFeedUrl': origin + '/feed/' + identifier + '.am.xml', 'subscriptions': history}
    for variant, key in [('normal', 'feedUrl'), ('am', 'amFeedUrl')]:
        latest = next((item for item in history if item['variant'] == variant), None)
        if latest:
            result[key] = latest['url']
    return result
