# -*- coding: utf-8 -*-
"""
/***************************************************************************
    begin                :    14/03/18
    git sha              :    :%H$
    copyright            :    (C) 2017 by Yesid Polanía (BSF-Swissphoto)
    email                :    yesidpol.3@gmail.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

import re
import pyodbc
from .db_connector import DBConnector


METADATA_TABLE = 't_ili2db_table_prop'

class MssqlConnector(DBConnector):
    '''SuperClass for all DB connectors.'''

    def __init__(self, uri, schema):
        DBConnector.__init__(self, uri, schema)
        self.conn = pyodbc.connect(uri)
        self.schema = schema

        # TODO Este código no debe ir acá
        if self.schema is None:
            self.schema = 'dbo'
        
        self._bMetadataTable = self._metadata_exists()
        self.iliCodeName = 'iliCode'

    def map_data_types(self, data_type):
        data_type = data_type.lower()
        if 'timestamp' in data_type:
            return self.QGIS_DATE_TIME_TYPE
        elif 'date' in data_type:
            return self.QGIS_DATE_TYPE
        elif 'time' in data_type:
            return self.QGIS_TIME_TYPE

        return data_type.lower()

    def metadata_exists(self):
        return self._bMetadataTable
    
    def _metadata_exists(self):

        # TODO Falta el if del schema
        #if self.schema:
        # TODO hay una diferencia con la forma de obtener el cursor en pg
        cur = self.conn.cursor()

        query = """
            SELECT count(TABLE_NAME) as 'count'
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_TYPE = 'BASE TABLE'
                AND TABLE_SCHEMA = '{}'
                    AND TABLE_NAME = '{}'
        """.format(self.schema, METADATA_TABLE)

        cur.execute(query)

        return bool(cur.fetchone()[0])

    def get_tables_info(self):
        kind_settings_field = ''
        domain_left_join = ''
        schema_where = ''
        table_alias = ''
        alias_left_join = ''

        if self.schema:
            if self._bMetadataTable:
                kind_settings_field = "p.setting AS kind_settings,"
                table_alias = "alias.setting AS table_alias,"
                domain_left_join = """
                    LEFT JOIN		{}.T_ILI2DB_TABLE_PROP p
                        ON p.tablename = tbls.TABLE_NAME 
                        AND p.tag = 'ch.ehi.ili2db.tableKind' 
                              """.format(self.schema)
                alias_left_join = """
                    LEFT JOIN		{}.T_ILI2DB_TABLE_PROP as alias
                        on	alias.tablename = tbls.TABLE_NAME
                        AND alias.tag = 'ch.ehi.ili2db.dispName'
                               """.format(self.schema)
            schema_where = "AND tbls.TABLE_SCHEMA = '{}'".format(self.schema)

        cur = self.conn.cursor()

        query = """
            SELECT 
                tbls.TABLE_SCHEMA AS schemaname,
                tbls.TABLE_NAME AS tablename, 
                Col.Column_Name AS primary_key,
                clm.COLUMN_NAME AS geometry_column,
                g.srid AS srid,
                {kind_settings_field}
                {table_alias}
                g.geometry_type AS simple_type,
                null as formatted_type
            FROM
            INFORMATION_SCHEMA.TABLE_CONSTRAINTS Tab 
            INNER JOIN		INFORMATION_SCHEMA.CONSTRAINT_COLUMN_USAGE Col 
                on Col.Constraint_Name = Tab.Constraint_Name
                AND Col.Table_Name = Tab.Table_Name
                AND Col.CONSTRAINT_SCHEMA = Tab.CONSTRAINT_SCHEMA
            RIGHT JOIN		INFORMATION_SCHEMA.TABLES as tbls
                on Tab.TABLE_NAME = tbls.TABLE_NAME 
                AND Tab.CONSTRAINT_SCHEMA = tbls.TABLE_SCHEMA
                AND Tab.Constraint_Type = 'PRIMARY KEY'
            {domain_left_join}
            {alias_left_join}
            LEFT JOIN		INFORMATION_SCHEMA.COLUMNS as clm
                on clm.TABLE_NAME = tbls.TABLE_NAME
                AND clm.TABLE_SCHEMA = tbls.TABLE_SCHEMA
                AND clm.DATA_TYPE = 'geometry'
            LEFT JOIN		dbo.geometry_columns g
                ON g.f_table_schema = clm.TABLE_SCHEMA
                AND g.f_table_name = clm.TABLE_NAME
                AND g.f_geometry_column = clm.COLUMN_NAME
            WHERE tbls.TABLE_TYPE = 'BASE TABLE' {schema_where}
        """.format(kind_settings_field=kind_settings_field, table_alias=table_alias,
                   domain_left_join=domain_left_join, alias_left_join=alias_left_join,
                   schema_where=schema_where)
                   
        cur.execute(query)

        columns = [column[0] for column in cur.description]

        res = []
        for row in cur.fetchall():
            my_rec = dict(zip(columns, row))
            # TODO type != simple_type
            my_rec['type'] = my_rec['simple_type']
            res.append(my_rec)

        return res

    # TODO pendiente regex

    def get_fields_info(self, table_name):
        # Get all fields for this table
        fields_cur = self.conn.cursor()

        # TODO falta la columna description
        # XXX informacion desde INFORMATION_SCHEMA

        query = """
            SELECT column_name
                ,data_type
                ,'------' AS comment
                ,unit.setting AS unit
                ,txttype.setting AS texttype
                ,alias.setting AS column_alias
            FROM INFORMATION_SCHEMA.COLUMNS AS c
            LEFT JOIN {schema}.t_ili2db_column_prop unit ON c.table_name = unit.tablename
                AND c.column_name = unit.columnname
                AND unit.tag = 'ch.ehi.ili2db.unit'
            LEFT JOIN {schema}.t_ili2db_column_prop txttype ON c.table_name = txttype.tablename
                AND c.column_name = txttype.columnname
                AND txttype.tag = 'ch.ehi.ili2db.textKind'
            LEFT JOIN {schema}.t_ili2db_column_prop alias ON c.table_name = alias.tablename
                AND c.column_name = alias.columnname
                AND alias.tag = 'ch.ehi.ili2db.dispName'
            WHERE TABLE_NAME = '{table}'
                AND TABLE_SCHEMA = '{schema}'
            """.format(schema=self.schema, table=table_name)

        fields_cur.execute(query)

        res = self._get_dict_result(fields_cur)

        return res

    def get_constraints_info(self, table_name):
        # Get all 'c'heck constraints for this table
        if self.schema:
            constraints_cur = self.conn.cursor()
            
            query = """
                SELECT CHECK_CLAUSE
                FROM
                    INFORMATION_SCHEMA.CHECK_CONSTRAINTS cc INNER JOIN
                    INFORMATION_SCHEMA.CONSTRAINT_COLUMN_USAGE c
                        ON cc.CONSTRAINT_NAME = c.CONSTRAINT_NAME
                        AND cc.CONSTRAINT_SCHEMA = c.CONSTRAINT_SCHEMA
                WHERE
                    cc.CONSTRAINT_SCHEMA = '{schema}'
                    AND TABLE_NAME = '{table}'
                """.format(schema=self.schema, table=table_name)
            
            constraints_cur.execute(query)

            # Create a mapping in the form of
            #
            # fieldname: (min, max)
            constraint_mapping = dict()
            for constraint in constraints_cur:
                m = re.match(r"\(\[(.*)\]>=\(([+-]?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)\) AND \[(.*)\]<=\(([+-]?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)\)\)", constraint[0])
                
                if m:
                    constraint_mapping[m.group(1)] = (
                    m.group(2), m.group(4))
                    
            return constraint_mapping

        return {}

    def get_relations_info(self, filter_layer_list=[]):
        cur = self.conn.cursor()
        schema_where1 = "AND KCU1.CONSTRAINT_SCHEMA = '{}'".format(
            self.schema) if self.schema else ''
        schema_where2 = "AND KCU2.CONSTRAINT_SCHEMA = '{}'".format(
            self.schema) if self.schema else ''
        filter_layer_where = ""
        if filter_layer_list:
            filter_layer_where = "AND KCU1.TABLE_NAME IN ('{}')".format("','".join(filter_layer_list))
        
        query = """
            SELECT  
                KCU1.CONSTRAINT_NAME AS constraint_name 
                ,KCU1.TABLE_NAME AS referencing_table 
                ,KCU1.COLUMN_NAME AS referencing_column 
                -- ,KCU2.CONSTRAINT_NAME AS REFERENCED_CONSTRAINT_NAME 
                ,KCU2.TABLE_NAME AS referenced_table 
                ,KCU2.COLUMN_NAME AS referenced_column 
                ,KCU1.ORDINAL_POSITION AS ordinal_position 
                -- ,KCU2.ORDINAL_POSITION AS REFERENCED_ORDINAL_POSITION 
            FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS AS RC 

            INNER JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE AS KCU1 
                ON KCU1.CONSTRAINT_CATALOG = RC.CONSTRAINT_CATALOG  
                AND KCU1.CONSTRAINT_SCHEMA = RC.CONSTRAINT_SCHEMA 
                AND KCU1.CONSTRAINT_NAME = RC.CONSTRAINT_NAME 

            INNER JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE AS KCU2 
                ON KCU2.CONSTRAINT_CATALOG = RC.UNIQUE_CONSTRAINT_CATALOG  
                AND KCU2.CONSTRAINT_SCHEMA = RC.UNIQUE_CONSTRAINT_SCHEMA 
                AND KCU2.CONSTRAINT_NAME = RC.UNIQUE_CONSTRAINT_NAME 
                AND KCU2.ORDINAL_POSITION = KCU1.ORDINAL_POSITION
            WHERE 1=1 {schema_where1} {schema_where2} {filter_layer_where}
            order by constraint_name, ordinal_position
            """.format(schema_where1=schema_where1, schema_where2=schema_where2, filter_layer_where=filter_layer_where)

        cur.execute(query)

        return self._get_dict_result(cur)

    def get_domainili_domaindb_mapping(self, domains):
        """TODO: remove when ili2db issue #19 is solved"""
        # Map domain ili name with its correspondent pg name
        cur = self.conn.cursor()
        domain_names = "'" + "','".join(domains) + "'"
        cur.execute("""SELECT iliname, sqlname
                        FROM {schema}.t_ili2db_classname
                        WHERE sqlname IN ({domain_names})
                    """.format(schema=self.schema, domain_names=domain_names))
        
        res = self._get_dict_result(cur)
        return res

    def get_models(self):
        """TODO: remove when ili2db issue #19 is solved"""
        # Get MODELS
        cur = self.conn.cursor()
        cur.execute("""SELECT modelname, content
                       FROM {schema}.t_ili2db_model
                    """.format(schema=self.schema))
        return self._get_dict_result(cur)

    def get_classili_classdb_mapping(self, models_info, extended_classes):
        """TODO: remove when ili2db issue #19 is solved"""
        cur = self.conn.cursor()
        class_names = "'" + \
            "','".join(list(models_info.keys()) +
                       list(extended_classes.keys())) + "'"

        # XXX Se presentaba error en lista de columnas con asterisco por problemas com mayusculas
        cur.execute("""SELECT iliname, sqlname
                       FROM {schema}.t_ili2db_classname
                       WHERE iliname IN ({class_names})
                    """.format(schema=self.schema, class_names=class_names))
        return self._get_dict_result(cur)

    def get_attrili_attrdb_mapping(self, models_info_with_ext):
        """TODO: remove when ili2db issue #19 is solved"""
        cur = self.conn.cursor()
        all_attrs = list()
        for c, dict_attr_domain in models_info_with_ext.items():
            all_attrs.extend(list(dict_attr_domain.keys()))
        attr_names = "'" + "','".join(all_attrs) + "'"
        cur.execute("""SELECT iliname, sqlname, owner
                       FROM {schema}.t_ili2db_attrname
                       WHERE iliname IN ({attr_names})
                    """.format(schema=self.schema, attr_names=attr_names))
        return self._get_dict_result(cur)

    def _get_dict_result(self, cur):
        columns = [column[0] for column in cur.description]

        res = []
        for row in cur.fetchall():
            my_rec = dict(zip(columns, row))
            res.append(my_rec)

        return res

