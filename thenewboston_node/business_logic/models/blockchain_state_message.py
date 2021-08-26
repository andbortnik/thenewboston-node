import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Type, TypeVar

from thenewboston_node.business_logic.models import AccountState
from thenewboston_node.business_logic.models.base import BaseDataclass
from thenewboston_node.business_logic.models.mixins.message import MessageMixin
from thenewboston_node.business_logic.validators import (
    validate_gte_value, validate_is_none, validate_not_none, validate_type
)
from thenewboston_node.core.logging import validates
from thenewboston_node.core.utils.dataclass import cover_docstring, revert_docstring
from thenewboston_node.core.utils.types import hexstr

logger = logging.getLogger(__name__)

T = TypeVar('T', bound='BlockchainStateMessage')


@revert_docstring
@dataclass
@cover_docstring
class BlockchainStateMessage(MessageMixin, BaseDataclass):

    account_states: dict[hexstr, AccountState] = field(
        metadata={'example_value': {
            '00f3d2477317d53bcc2a410decb68c769eea2f0d74b679369b7417e198bd97b6': {}
        }}
    )
    """Account number to account state map"""

    last_block_number: Optional[int] = field(default=None, metadata={'example_value': 5})
    """Number of the last block included into the blockchain state (optional for blockchain genesis state)"""

    # TODO(dmu) MEDIUM: Do we really need last_block_identifier?
    last_block_identifier: Optional[hexstr] = field(
        default=None, metadata={'example_value': 'b0dabd367eb1ed670ab9ce4cef9d45106332f211c7b50ddd60dec4ae62711fb7'}
    )
    """Identifier of the last block included into the blockchain state (optional for blockchain genesis state)"""

    # TODO(dmu) HIGH: Do we really need `last_block_timestamp`?
    last_block_timestamp: Optional[datetime] = field(
        default=None, metadata={'example_value': datetime(2021, 5, 19, 10, 34, 5, 54106)}
    )
    """Timestamp of the last block included into the blockchain state (optional for blockchain genesis state)"""

    next_block_identifier: Optional[hexstr] = field(
        default=None, metadata={'example_value': 'dc6671e1132cbb7ecbc190bf145b5a5cfb139ca502b5d66aafef4d096f4d2709'}
    )
    """Identifier of the next block to be added on top of the blockchain state
    (optional for blockchain genesis state, blockchain state hash is used as next block identifier in this case)"""

    @classmethod
    def deserialize_from_dict(
        cls: Type[T], dict_, complain_excessive_keys=True, override: Optional[dict[str, Any]] = None
    ) -> T:
        override = override or {}
        if 'account_states' in dict_ and 'account_states' not in override:
            # Replace null value of node.identifier with account number
            account_states = dict_.pop('account_states')
            account_state_objects = {}
            for account_number, account_state in account_states.items():
                account_state_object = AccountState.deserialize_from_dict(account_state)
                if (node := account_state_object.node) and node.identifier is None:
                    node.identifier = account_number
                account_state_objects[account_number] = account_state_object

            override['account_states'] = account_state_objects

        return super().deserialize_from_dict(dict_, override=override)

    def serialize_to_dict(self, skip_none_values=True, coerce_to_json_types=True, exclude=()):
        serialized = super().serialize_to_dict(
            skip_none_values=skip_none_values, coerce_to_json_types=coerce_to_json_types, exclude=exclude
        )
        for account_number, account_state in serialized['account_states'].items():
            if account_state.get('balance_lock') == account_number:
                del account_state['balance_lock']

            if node := account_state.get('node'):
                node.pop('identifier', None)

        return serialized

    @validates('blockchain state')
    def validate(self, is_initial=False):
        self.validate_attributes(is_initial=is_initial)
        self.validate_accounts()

    @validates('blockchain state attributes', is_plural_target=True)
    def validate_attributes(self, is_initial=False):
        self.validate_last_block_number(is_initial)
        self.validate_last_block_identifier(is_initial)
        self.validate_last_block_timestamp(is_initial)
        self.validate_next_block_identifier(is_initial)

    @validates('blockchain state last_block_number')
    def validate_last_block_number(self, is_initial):
        if is_initial:
            validate_is_none(f'Initial {self.humanized_class_name} last_block_number', self.last_block_number)
        else:
            validate_type(f'{self.humanized_class_name} last_block_number', self.last_block_number, int)
            validate_gte_value(f'{self.humanized_class_name} last_block_number', self.last_block_number, 0)

    @validates('blockchain state last_block_identifier')
    def validate_last_block_identifier(self, is_initial):
        if is_initial:
            validate_is_none(f'Initial {self.humanized_class_name} last_block_identifier', self.last_block_identifier)
        else:
            validate_not_none(f'{self.humanized_class_name} last_block_identifier', self.last_block_identifier)
            validate_type(f'{self.humanized_class_name} last_block_identifier', self.last_block_identifier, str)

    @validates('blockchain state last_block_timestamp')
    def validate_last_block_timestamp(self, is_initial):
        timestamp = self.last_block_timestamp
        if is_initial:
            validate_is_none(f'Initial {self.humanized_class_name} last_block_timestamp', timestamp)
        else:
            validate_not_none(f'{self.humanized_class_name} last_block_timestamp', timestamp)
            validate_type(f'{self.humanized_class_name} last_block_timestamp', timestamp, datetime)
            validate_is_none(f'{self.humanized_class_name} last_block_timestamp timezone', timestamp.tzinfo)

    @validates('blockchain state next_block_identifier')
    def validate_next_block_identifier(self, is_initial):
        if is_initial:
            validate_is_none(f'Initial {self.humanized_class_name} next_block_identifier', self.next_block_identifier)
        else:
            validate_type(f'{self.humanized_class_name} next_block_identifier', self.next_block_identifier, str)

    @validates('blockchain state accounts', is_plural_target=True)
    def validate_accounts(self):
        for account, balance in self.account_states.items():
            with validates(f'blockchain state account {account}'):
                validate_type(f'{self.humanized_class_name} account', account, str)
                balance.validate()
