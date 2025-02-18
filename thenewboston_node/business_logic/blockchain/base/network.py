import logging
from typing import Optional

from thenewboston_node.business_logic.models import Node
from thenewboston_node.core.utils.types import hexstr

from .base import BaseMixin

logger = logging.getLogger(__name__)


class NetworkMixin(BaseMixin):

    def get_node_by_identifier(self, identifier: hexstr, on_block_number: Optional[int] = None) -> Optional[Node]:
        if on_block_number is None:
            on_block_number = self.get_last_block_number()
        return self.get_account_state_attribute_value(identifier, 'node', on_block_number)

    def yield_nodes(self, block_number: Optional[int] = None):
        known_accounts = set()
        for account_number, account_state in self.yield_account_states(from_block_number=block_number):
            node = account_state.node
            if not node:
                continue

            if account_number in known_accounts:
                continue

            known_accounts.add(account_number)
            yield node

    def has_nodes(self):
        return any(self.yield_nodes())

    def get_primary_validator(self, block_number: Optional[int] = None) -> Optional[Node]:
        if block_number is None:
            block_number = self.get_next_block_number()

        # We get last_block_number and blockchain_state here to avoid race conditions. Do not change it
        last_block_number = self.get_last_block_number()
        blockchain_state = self.get_blockchain_state_by_block_number(
            last_block_number, inclusive=last_block_number > -1
        )
        for block in self.yield_blocks_slice_reversed(last_block_number, blockchain_state.get_last_block_number()):
            for account_number, account_state in block.yield_account_states():
                pv_schedule = account_state.primary_validator_schedule
                if pv_schedule and pv_schedule.is_block_number_included(block_number):
                    return self.get_node_by_identifier(account_number)

        # TODO(dmu) HIGH: Once we have more accounts this method will become slow. We need to optimize it
        #                 by caching
        for account_number, account_state in blockchain_state.yield_account_states():
            pv_schedule = account_state.primary_validator_schedule
            if pv_schedule and pv_schedule.is_block_number_included(block_number):
                return self.get_node_by_identifier(account_number)

        return None
