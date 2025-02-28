# Copyright Elasticsearch B.V. and/or licensed to Elasticsearch B.V. under one
# or more contributor license agreements. Licensed under the Elastic License 2.0;
# you may not use this file except in compliance with the Elastic License 2.0.

from typing import Any, Optional

from share import Config, ElasticsearchOutput, Input, Output, shared_logger
from shippers import ProtocolShipper, ShipperFactory

from .exceptions import InputConfigException, OutputConfigException, ReplayHandlerException
from .utils import delete_sqs_record


class ReplayedEventReplayHandler:
    def __init__(self, replay_queue_arn: str):
        self._replay_queue_arn = replay_queue_arn
        self._failed_event_ids: list[str] = []
        self._event_ids_with_receipt_handle: dict[str, str] = {}

    def add_event_id_with_receipt_handle(self, event_id: str, receipt_handle: str) -> None:
        self._event_ids_with_receipt_handle[event_id] = receipt_handle

    def replay_handler(self, output_type: str, output_args: dict[str, Any], event_payload: dict[str, Any]) -> None:
        self._failed_event_ids.append(event_payload["_id"])

    def flush(self) -> None:
        for failed_event_id in self._failed_event_ids:
            del self._event_ids_with_receipt_handle[failed_event_id]

        for receipt_handle in self._event_ids_with_receipt_handle.values():
            delete_sqs_record(self._replay_queue_arn, receipt_handle)

        if len(self._failed_event_ids) > 0:
            raise ReplayHandlerException()


def get_shipper_for_replay_event(
    config: Config,
    output_type: str,
    output_args: dict[str, Any],
    event_input_id: str,
    replay_handler: ReplayedEventReplayHandler,
) -> Optional[ProtocolShipper]:
    event_input: Optional[Input] = config.get_input_by_id(event_input_id)
    if event_input is None:
        raise InputConfigException(f"Cannot load input for input id {event_input_id}")

    output: Optional[Output] = event_input.get_output_by_type(output_type)
    if output is None:
        raise OutputConfigException(f"Cannot load output of type {output_type}")

    if output_type == "elasticsearch":
        assert isinstance(output, ElasticsearchOutput)
        output.es_datastream_name = output_args["es_datastream_name"]
        shared_logger.info("setting ElasticSearch shipper")
        elasticsearch: ProtocolShipper = ShipperFactory.create_from_output(output_type=output_type, output=output)
        elasticsearch.set_replay_handler(replay_handler=replay_handler.replay_handler)

        return elasticsearch

    return None
