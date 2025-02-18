import json
import logging
from contextlib import closing
from urllib.request import urlopen

from django.conf import settings

from thenewboston_node.business_logic.models import AccountState, BlockchainState
from thenewboston_node.business_logic.models.signed_change_request_message.pv_schedule import PrimaryValidatorSchedule
from thenewboston_node.core.utils.misc import is_valid_url

logger = logging.getLogger()


def read_source(source):
    if is_valid_url(source):
        fp = urlopen(source)
    else:
        fp = open(source)

    with closing(fp) as fp:
        return json.load(fp)


def add_blockchain_state_from_account_root_file(blockchain, source, first_node):
    message = f'Reading account root file from {source}'
    logger.info(message)
    account_root_file = read_source(source)
    logger.info('DONE: %s', message)

    logger.info('Converting')
    blockchain_state = BlockchainState.create_from_account_root_file(account_root_file)
    logger.info('DONE: Converting')

    node_identifier = first_node.identifier
    logger.info('Injecting node %s', node_identifier)
    account_state = blockchain_state.get_account_state(node_identifier)
    if account_state is None:
        account_state = AccountState()
        blockchain_state.set_account_state(node_identifier, account_state)

    account_state.node = first_node
    account_state.primary_validator_schedule = PrimaryValidatorSchedule(
        begin_block_number=0, end_block_number=settings.SCHEDULE_DEFAULT_LENGTH_IN_BLOCKS - 1
    )

    logger.info('DONE: Injecting node')

    logger.info('Adding the blockchain state')
    blockchain.add_blockchain_state(blockchain_state)
    logger.info('DONE: Adding the blockchain state')
