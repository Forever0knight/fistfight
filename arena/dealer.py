import os
import json

import gevent
import redis
from flask import Blueprint

from arena.database import DatabaseServices
from arena.game import punch

bp = Blueprint('dealer', __name__)

REDIS_URL = os.environ['REDIS_URL']

redis = redis.from_url(REDIS_URL)

@bp.route('/<string:room_name>/submit')
def inbox(ws, room_name):
    """Receives incoming player messages, inserts them into Redis."""
    while not ws.closed:
        # Sleep to prevent *contstant* context-switches.
        gevent.sleep(0.1)
        message = ws.receive()
        if message:
            data = json.loads(message)
            # TODO: extract these
            if data['action'] == "punch":
                punch_result = punch(data["attacker"], data["attackee"])
                data['result_message'] = punch_result["message"]
                data['damage'] = punch_result["damage"]
            elif data["action"] == "join-game":
                print("%s is attempting to join the game." % data['figure_name'])
                figure_name = data['figure_name']
                print("trying to get game_id %s" % data['game_id'])
                game_id = data['game_id']
                print("figure_name: %s, game_id: %s" % (figure_name, game_id))
                with DatabaseServices() as db:
                    figure = json.loads(db.get_figure_by_name(figure_name))[0]
                with DatabaseServices() as db:
                    db.add_figure_to_game(figure['figure_name'], game_id)
                with DatabaseServices() as db:
                    players = db.get_figures_by_game_id(game_id)
                data["players"] = players
                data["result_message"] = u'figure_name: {}, game_id: {}'.format(figure, game_id)
            message = json.dumps(data)
            print(u'Inserting message: {}'.format(message))
            redis.publish(room_name, message)

@bp.route('/<string:room_name>/receive')
def outbox(ws, room_name):
    """Sends outgoing chat messages, via `Dealer`."""
    dealer = Dealer(room_name)
    dealer.start()
    dealer.register(ws)

    while not ws.closed:
        # Context switch while `ChatBackend.start` is running in the background.
        gevent.sleep(0.1)


class Dealer(object):
    """Interface for registering and updating WebSocket clients."""

    def __init__(self, room_name):
        self.clients = list()
        self.pubsub = redis.pubsub()
        self.pubsub.subscribe(room_name)
        

    def __iter_data(self):
        for message in self.pubsub.listen():
            data = message.get('data')
            if message['type'] == 'message':
                print(u'Sending message: {}'.format(data))
                yield data

    def register(self, client):
        """Register a WebSocket connection for Redis updates."""
        self.clients.append(client)

    def send(self, client, data):
        """Send given data to the registered client.
        Automatically discards invalid connections."""
        try:
            client.send(data)
        except Exception:
            self.clients.remove(client)
            raise

    def run(self):
        """Listens for new messages in Redis, and sends them to clients."""
        for data in self.__iter_data():
            for client in self.clients:
                gevent.spawn(self.send, client, data)

    def start(self):
        """Maintains Redis subscription in the background."""
        gevent.spawn(self.run)