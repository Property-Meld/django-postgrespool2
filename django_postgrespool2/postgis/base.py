from ..base import *

from django.contrib.gis.db.backends.postgis.base import *
from django.contrib.gis.db.backends.postgis.base import DatabaseWrapper as Psycopg2DatabaseWrapper
from django.contrib.gis.db.backends.postgis.schema import PostGISSchemaEditor as DatabaseSchemaEditor
from django.contrib.gis.db.backends.postgis.introspection import PostGISIntrospection as DatabaseIntrospection
from django.contrib.gis.db.backends.postgis.operations import PostGISOperations as DatabaseOperations
from django.contrib.gis.db.backends.postgis.features import DatabaseFeatures as DatabaseFeatures
from django.db.backends.postgresql.creation import DatabaseCreation as Psycopg2DatabaseCreation


class DatabaseWrapper(Psycopg2DatabaseWrapper):

    def __init__(self, *args, **kwargs):
        super(DatabaseWrapper, self).__init__(*args, **kwargs)
        self._pool = None
        self._pool_connection = None
        self.creation = DatabaseCreation(self)

    @property
    def pool(self):
        return self._pool

    def _close(self):
        if self._pool_connection is not None:
            if not self.is_usable():
                self._pool_connection.invalidate()
            with self.wrap_database_errors:
                return self._pool_connection.close()

    @async_unsafe
    def create_cursor(self, name=None):
        if name:
            # In autocommit mode, the cursor will be used outside of a
            # transaction, hence use a holdable cursor.
            cursor = self._pool_connection.cursor(
                name, scrollable=False, withhold=self.connection.autocommit)
        else:
            cursor = self._pool_connection.cursor()
        cursor.tzinfo_factory = self.tzinfo_factory if settings.USE_TZ else None
        return cursor

    def tzinfo_factory(self, offset):
        if utc_tzinfo_factory:
            # for Django 2.2
            return utc_tzinfo_factory(offset)
        return self.timezone

    def dispose(self):
        """
        Dispose of the pool for this instance, closing all connections.
        """
        self.close()
        self._pool_connection = None
        # _DBProxy.dispose doesn't actually call dispose on the pool
        if self.pool:
            self.pool.dispose()
            self._pool = None
        conn_params = self.get_connection_params()
        db_pool.dispose(**conn_params)
        pool_disposed.send(sender=self.__class__, connection=self)

    @async_unsafe
    def get_new_connection(self, conn_params):
        if not self._pool:
            self._pool = db_pool.get_pool(**conn_params)
        # get new connection through pool, not creating a new one outside.
        self._pool_connection = self.pool.connect()
        c = self._pool_connection.connection  # dbapi connection

        options = self.settings_dict['OPTIONS']
        try:
            self.isolation_level = options['isolation_level']
        except KeyError:
            self.isolation_level = c.isolation_level
        else:
            # Set the isolation level to the value from OPTIONS.
            if self.isolation_level != c.isolation_level:
                c.set_session(isolation_level=self.isolation_level)

        if django_version >= (3, 1, 1):
            psycopg2.extras.register_default_jsonb(conn_or_curs=c, loads=lambda x: x)
        return c

    def is_usable(self):
        if not self.connection:
            return False
        return self.connection.closed == 0
