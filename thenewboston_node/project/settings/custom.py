# File for Node-specific logic settings
SENTRY_DSN = None
IS_LOCAL_SETTINGS_FILE_APPLIED = False
TEST_WITH_ENV_VARS = False

NODE_SIGNING_KEY = NotImplemented
NODE_SCHEME = 'http'
NODE_PORT = 8555
APPEND_AUTO_DETECTED_NETWORK_ADDRESS = True
NODE_NETWORK_ADDRESSES: list[str] = []
NODE_FEE_AMOUNT = 3
NODE_FEE_ACCOUNT = None

SCHEDULE_DEFAULT_LENGTH_IN_BLOCKS = 100

NETWORK = {
    'class': 'thenewboston_node.business_logic.network.tcp_network.TCPNetwork',
    'kwargs': {},
}

MEMO_MAX_LENGTH = 64
