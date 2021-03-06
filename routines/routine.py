"""
Routine Class

The code is licensed under the MIT license.
"""

import os
from ftplib import FTP
from sqlalchemy import create_engine, text
from configparser import ConfigParser
import pandas as pd


class Routine():

    """
    Generic logic which is used across different kinds of routines.
    """

    # Name of the routine
    name: str = None

    # Path of configuration file
    config_path: str = os.path.expanduser(
        '~') + os.sep + '.routines' + os.sep + 'config.txt'

    # The config
    config = None

    # System database connection
    sys_db = None

    # Meteostat database connection
    db = None

    # Bulk FTP connection
    bulk_ftp = None

    def _connect(self) -> None:

        # System database connection
        sys_db = create_engine(
            f"""mysql+mysqlconnector://{self.config.get('sys_db', 'user')}:{self.config.get('sys_db', 'password')}@{self.config.get('sys_db', 'host')}/{self.config.get('sys_db', 'name')}?charset=utf8""")
        self.sys_db = sys_db

        # Meteostat database connection
        db = create_engine(
            f"""mysql+mysqlconnector://{self.config.get('database', 'user')}:{self.config.get('database', 'password')}@{self.config.get('database', 'host')}/{self.config.get('database', 'name')}?charset=utf8""")
        self.db = db

    def _connect_worldclim(self) -> None:

        # WorldClim database connection
        db = create_engine(
            f"""mysql+mysqlconnector://{self.config.get('worldclim', 'user')}:{self.config.get('worldclim', 'password')}@{self.config.get('worldclim', 'host')}/{self.config.get('worldclim', 'name')}?charset=utf8""")
        self.worldclim_db = db

    def _connect_bulk(self) -> None:

        # Configuration file
        config = ConfigParser()
        config.read(self.config_path)

        # FTP connection
        self.bulk_ftp = FTP(self.config.get('bulk_ftp', 'host'))
        self.bulk_ftp.login(self.config.get('bulk_ftp', 'user'), self.config.get('bulk_ftp', 'password'))

    def __init__(
        self,
        name: str,
        connect_bulk: bool = False,
        connect_worldclim: bool = False
    ) -> None:

        # Meta data
        self.name = name

        # Configuration file
        self.config = ConfigParser()
        self.config.read(self.config_path)

        # Database connections
        self._connect()

        # Bulk FTP connection
        if connect_bulk:
            self._connect_bulk()

        # WorldClim DB connection
        if connect_worldclim:
            self._connect_worldclim()

    def set_var(self, name: str, value: str) -> None:

        payload = {
            'ctx': self.name,
            'name': name,
            'value': str(value)
        }

        with self.sys_db.connect() as con:
            con.execute(
                text("""INSERT INTO `variables`(`ctx`, `name`, `value`) VALUES (:ctx, :name, :value) ON DUPLICATE KEY UPDATE `value` = :value"""),
                payload)

    def get_var(self, name: str) -> str:

        payload = {
            'ctx': self.name,
            'name': name
        }

        with self.sys_db.connect() as con:
            result = con.execute(
                text(
                    """SELECT `value` FROM `variables` WHERE `ctx` = :ctx AND `name` = :name LIMIT 1"""),
                payload)

        if result.rowcount == 1:
            return result.first()[0]
        else:
            return None

    def get_stations(self, query: str, limit: int) -> list:

        # Get counter value
        counter = self.get_var('station_counter')
        skip = 0 if counter is None else int(counter)

        # Get weather stations
        with self.db.connect() as con:
            result = con.execute(text(query + f" LIMIT {skip}, {limit}"))

        # Update counter
        if result.rowcount < limit:
            self.set_var('station_counter', 0)
        else:
            self.set_var('station_counter', skip + limit)

        return result.fetchall()

    def write(self, data: pd.DataFrame, schema: dict) -> None:

        # Validations
        for parameter, validation in schema['validation'].items():
            if parameter in data.columns:
                data[parameter] = data[parameter].apply(validation)

        # NaN to None
        data = data.where(pd.notnull(data), None)

        # Remove rows with NaN only
        data = data.dropna(axis=0, how='all')

        # Convert time data to String
        data.index = data.index.set_levels(
            data.index.levels[1].astype(str), level=1)

        with self.db.begin() as con:
            for record in data.reset_index().to_dict(orient='records'):
                con.execute(text(schema['import_query']), {
                            **schema['template'], **record})

    def read(self, query: str, payload: dict = {}):

        with self.db.connect() as con:
            return con.execute(text(query).execution_options(autocommit=True), payload)

    def query(self, query: str, payload: dict = {}):

        with self.db.connect() as con:
            con.execute(text(query).execution_options(autocommit=True), payload)
