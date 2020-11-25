#! /usr/bin/env python3

import time
import logging
import yaml
import sqlite3
import os
from governor.storage import GovernorStorage

from juju.controller import Controller
from juju.client import client
from juju import loop


snap_common = os.getenv("SNAP_COMMON")


async def connect_juju_components(endpoint, username, password, cacert, model_name):
    """ Connect to controller and model """
    ctrl = Controller()
    await ctrl.connect(
        endpoint=endpoint, username=username, password=password, cacert=cacert
    )

    model = await ctrl.get_model(model_name)

    return ctrl, model


async def unit_watcher(model, entity_type, governor_charm):
    """ Watch all changes in units """
    allwatcher = client.AllWatcherFacade.from_connection(model.connection())

    change = await allwatcher.Next()
    event_list = []

    while True:
        units = model.units
        time.sleep(2)
        change = await allwatcher.Next()
        for delta in change.deltas:
            delta_entity = None

            delta_entity = delta.entity

            if delta_entity == "unit":

                if delta.type == "change" and delta.data["name"] not in units:
                    logging.warning("New unit was added")

                    event_data = {
                        "event_name": "unit_added",
                        "event_data": {"unit_name": delta.data["name"]},
                    }

                    event_list.append(event_data)
                    logging.warning("Action executed")

                if delta.type == "remove":
                    logging.warning("Unit was removed")
                    event_data = {
                        "event_name": "unit_removed",
                        "event_data": {"unit_name": delta.data["name"]},
                    }
                    event_list.append(event_data)
                    logging.warning("Action executed")

            if event_list:
                event_list = await events_to_storage(model, event_list, governor_charm)


async def events_to_storage(model, event_list, governor_charm):
    """
    Store events to Governor Storage if unlocked and wake up governor charm with action.
    """
    try:
        gs = GovernorStorage("{}/gs_db".format(snap_common))

        for i in range(len(event_list)):
            gs.write_event_data(event_list[0])
            event_list.pop(0)

        await execute_action(model, governor_charm, "governor-event")

        gs.close()
    except sqlite3.OperationalError:
        logging.warning("Waiting for DB to unlock")

    return event_list


async def execute_action(model, application_name, action_name, **kwargs):
    """ Execute action on leader unit of application. """
    if not model.applications and application_name not in model.applications:
        return

    application = model.applications[application_name]

    for u in application.units:
        if await u.is_leader_from_status():
            unit = u

    await unit.run_action(action_name, **kwargs)


async def govern_model(
    endpoint,
    username,
    password,
    cacert,
    model_name,
    governor_charm,
):
    """ Connect to juju components and call watchers. """
    _, model = await connect_juju_components(
        endpoint, username, password, cacert, model_name
    )

    await unit_watcher(model, "unit", governor_charm)


def main():
    """ Read credentials and call Govern Model. """
    with open("{}/creds.yaml".format(snap_common), "r") as stream:
        creds = yaml.safe_load(stream)

    loop.run(
        govern_model(
            creds["endpoint"],
            creds["username"],
            creds["password"],
            creds["cacert"],
            creds["model"],
            creds["governor-charm"],
        )
    )


if __name__ == "__main__":
    main()
