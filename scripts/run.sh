#!/usr/bin/env bash

set -e
cp -v thenewboston_node/project/settings/templates/nginx.conf /etc/nginx/conf.d/node.conf

poetry run python -m thenewboston_node.manage migrate

# TODO(dmu) MEDIUM: We do not really need to collect static, since we are using Whitenoise
poetry run python -m thenewboston_node.manage collectstatic

poetry run python -m thenewboston_node.manage initialize_blockchain ${INITIALIZE_BLOCKCHAIN_ARGS} ${ARF_URL} ${ARF_PATH}
poetry run daphne -b 0.0.0.0 thenewboston_node.project.asgi:application
