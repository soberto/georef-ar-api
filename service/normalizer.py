"""Módulo 'normalizer' de georef-api

Contiene funciones que manejan la lógica de procesamiento
de los recursos que expone la API.
"""

from service import data, params, formatter
from service import names as N
from flask import current_app
from contextlib import contextmanager


def get_elasticsearch():
    """Devuelve la conexión a Elasticsearch activa para la sesión
    de flask. La conexión es creada si no existía.

    Returns:
        Elasticsearch: conexión a Elasticsearch.

    Raises:
        data.DataConnectionException: En caso de ocurrir un error de
            conexión con la capa de manejo de datos.

    """
    if not hasattr(current_app, 'elasticsearch'):
        current_app.elasticsearch = data.elasticsearch_connection(
            hosts=current_app.config['ES_HOSTS'],
            sniff=current_app.config['ES_SNIFF'],
            sniffer_timeout=current_app.config['ES_SNIFFER_TIMEOUT']
        )

    return current_app.elasticsearch


def get_postgres_db_connection_pool():
    """Devuelve la pool de conexiones a PostgreSQL activa para la sesión
    de flask. La pool es creada si no existía.

    Returns:
        psycopg2.pool.ThreadedConnectionPool: Pool de conexiones.

    Raises:
        data.DataConnectionException: En caso de ocurrir un error de
            conexión con la capa de manejo de datos.

    """
    if not hasattr(current_app, 'postgres_pool'):
        current_app.postgres_pool = data.postgres_db_connection_pool(
            name=current_app.config['SQL_DB_NAME'],
            host=current_app.config['SQL_DB_HOST'],
            user=current_app.config['SQL_DB_USER'],
            password=current_app.config['SQL_DB_PASS'],
            maxconn=current_app.config['SQL_DB_MAX_CONNECTIONS']
        )

    return current_app.postgres_pool


@contextmanager
def get_postgres_db_connection(pool):
    connection = pool.getconn()
    try:
        yield connection
    finally:
        pool.putconn(connection)


def get_index_source(index):
    """Devuelve la fuente para un índice dado.

    Args:
        index (str): Nombre del índice.

    Returns:
        str: Nombre de la fuente.

    """
    if index in [N.STATES, N.DEPARTMENTS, N.MUNICIPALITIES]:
        return N.SOURCE_IGN
    elif index == N.LOCALITIES:
        return N.SOURCE_BAHRA
    elif index == N.STREETS:
        return N.SOURCE_INDEC
    else:
        raise ValueError(
            'No se pudo determinar la fuente de: {}'.format(index))


def translate_keys(d, translations, ignore=None):
    """Cambia las keys del diccionario 'd', utilizando las traducciones
    especificadas en 'translations'. Devuelve los resultados en un nuevo
    diccionario.

    Args:
        d (dict): Diccionario a modificar.
        translations (dict): Traducciones de keys (key anterior => key nueva.)
        ignore (list): Keys de 'd' a no agregar al nuevo diccionario devuelto.

    Returns:
        dict: Diccionario con las keys modificadas.

    """
    if not ignore:
        ignore = []

    return {
        translations.get(key, key): value
        for key, value in d.items()
        if key not in ignore
    }


def process_entity_single(request, name, param_parser, key_translations,
                          csv_fields):
    """Procesa una request GET para consultar datos de una entidad.
    En caso de ocurrir un error de parseo, se retorna una respuesta HTTP 400.

    Args:
        request (flask.Request): Request GET de flask.
        name (str): Nombre de la entidad.
        param_parser (ParameterSet): Objeto utilizado para parsear los
            parámetros.
        key_translations (dict): Traducciones de keys a utilizar para convertir
            el diccionario de parámetros del usuario a un diccionario
            representando una query a Elasticsearch.
        csv_fields (dict): Diccionario a utilizar para modificar los campos
            cuando se utiliza el formato CSV.

    Raises:
        data.DataConnectionException: En caso de ocurrir un error de
            conexión con la capa de manejo de datos.

    Returns:
        flask.Response: respuesta HTTP
    """
    try:
        qs_params = param_parser.parse_get_params(request.args)
    except params.ParameterParsingException as e:
        return formatter.create_param_error_response_single(e.errors)

    # Construir query a partir de parámetros
    query = translate_keys(qs_params, key_translations,
                           ignore=[N.FLATTEN, N.FORMAT])

    # Construir reglas de formato a partir de parámetros
    fmt = {
        key: qs_params[key]
        for key in [N.FLATTEN, N.FIELDS, N.FORMAT]
        if key in qs_params
    }
    fmt[N.CSV_FIELDS] = csv_fields

    es = get_elasticsearch()
    result = data.search_entities(es, name, [query])[0]

    source = get_index_source(name)
    for match in result:
        match[N.SOURCE] = source

    return formatter.create_ok_response(name, result, fmt)


def process_entity_bulk(request, name, param_parser, key_translations):
    """Procesa una request POST para consultar datos de una lista de entidades.
    En caso de ocurrir un error de parseo, se retorna una respuesta HTTP 400.

    Args:
        request (flask.Request): Request POST de flask.
        name (str): Nombre de la entidad.
        param_parser (ParameterSet): Objeto utilizado para parsear los
            parámetros.
        key_translations (dict): Traducciones de keys a utilizar para convertir
            los diccionarios de parámetros del usuario a una lista de
            diccionarios representando las queries a Elasticsearch.

    Raises:
        data.DataConnectionException: En caso de ocurrir un error de
            conexión con la capa de manejo de datos.

    Returns:
        flask.Response: respuesta HTTP
    """
    try:
        body_params = param_parser.parse_post_params(
            request.args, request.json and request.json.get(name))
    except params.ParameterParsingException as e:
        return formatter.create_param_error_response_bulk(e.errors)

    queries = []
    formats = []
    for parsed_params in body_params:
        # Construir query a partir de parámetros
        query = translate_keys(parsed_params, key_translations,
                               ignore=[N.FLATTEN, N.FORMAT])

        # Construir reglas de formato a partir de parámetros
        fmt = {
            key: parsed_params[key]
            for key in [N.FLATTEN, N.FIELDS]
            if key in parsed_params
        }

        queries.append(query)
        formats.append(fmt)

    es = get_elasticsearch()
    results = data.search_entities(es, name, queries)

    source = get_index_source(name)
    for result in results:
        for match in result:
            match[N.SOURCE] = source

    return formatter.create_ok_response_bulk(name, results, formats)


def process_entity(request, name, param_parser, key_translations, csv_fields):
    """Procesa una request GET o POST para consultar datos de una entidad.
    En caso de ocurrir un error de parseo, se retorna una respuesta HTTP 400.
    En caso de ocurrir un error interno, se retorna una respuesta HTTP 500.

    Args:
        request (flask.Request): Request GET o POST de flask.
        name (str): Nombre de la entidad.
        param_parser (ParameterSet): Objeto utilizado para parsear los
            parámetros.
        key_translations (dict): Traducciones de keys a utilizar para convertir
            los diccionarios de parámetros del usuario a una lista de
            diccionarios representando las queries a Elasticsearch.
        csv_fields (dict): Diccionario a utilizar para modificar los campos
            cuando se utiliza el formato CSV.

    Returns:
        flask.Response: respuesta HTTP
    """
    try:
        if request.method == 'GET':
            return process_entity_single(request, name, param_parser,
                                         key_translations, csv_fields)
        else:
            return process_entity_bulk(request, name, param_parser,
                                       key_translations)
    except data.DataConnectionException:
        return formatter.create_internal_error_response()


def process_state(request):
    """Procesa una request GET o POST para consultar datos de provincias.
    En caso de ocurrir un error de parseo, se retorna una respuesta HTTP 400.

    Args:
        request (flask.Request): Request GET o POST de flask.

    Returns:
        flask.Response: respuesta HTTP
    """
    return process_entity(request, N.STATES, params.PARAMS_STATES, {
            N.ID: 'entity_id',
            N.NAME: 'name',
            N.EXACT: 'exact',
            N.ORDER: 'order',
            N.FIELDS: 'fields'
    }, formatter.STATES_CSV_FIELDS)


def process_department(request):
    """Procesa una request GET o POST para consultar datos de departamentos.
    En caso de ocurrir un error de parseo, se retorna una respuesta HTTP 400.

    Args:
        request (flask.Request): Request GET o POST de flask.

    Returns:
        flask.Response: respuesta HTTP
    """
    return process_entity(request, N.DEPARTMENTS,
                          params.PARAMS_DEPARTMENTS, {
                              N.ID: 'entity_id',
                              N.NAME: 'name',
                              N.STATE: 'state',
                              N.EXACT: 'exact',
                              N.ORDER: 'order',
                              N.FIELDS: 'fields'
                          }, formatter.DEPARTMENTS_CSV_FIELDS)


def process_municipality(request):
    """Procesa una request GET o POST para consultar datos de municipios.
    En caso de ocurrir un error de parseo, se retorna una respuesta HTTP 400.

    Args:
        request (flask.Request): Request GET o POST de flask.

    Returns:
        flask.Response: respuesta HTTP
    """
    return process_entity(request, N.MUNICIPALITIES,
                          params.PARAMS_MUNICIPALITIES, {
                              N.ID: 'entity_id',
                              N.NAME: 'name',
                              N.STATE: 'state',
                              N.DEPT: 'department',
                              N.EXACT: 'exact',
                              N.ORDER: 'order',
                              N.FIELDS: 'fields'
                          }, formatter.MUNICIPALITIES_CSV_FIELDS)


def process_locality(request):
    """Procesa una request GET o POST para consultar datos de localidades.
    En caso de ocurrir un error de parseo, se retorna una respuesta HTTP 400.

    Args:
        request (flask.Request): Request GET o POST de flask.

    Returns:
        flask.Response: respuesta HTTP
    """
    return process_entity(request, N.LOCALITIES, params.PARAMS_LOCALITIES, {
            N.ID: 'entity_id',
            N.NAME: 'name',
            N.STATE: 'state',
            N.DEPT: 'department',
            N.MUN: 'municipality',
            N.EXACT: 'exact',
            N.ORDER: 'order',
            N.FIELDS: 'fields'
    }, formatter.LOCALITIES_CSV_FIELDS)


def build_street_query_format(parsed_params):
    """Construye dos diccionarios a partir de parámetros de consulta
    recibidos, el primero representando la query a Elasticsearch a
    realizar y el segundo representando las propiedades de formato
    (presentación) que se le debe dar a los datos obtenidos de la misma.

    Args:
        parsed_params (dict): Parámetros de una consulta para el índice de
            calles.

    Returns:
        tuple: diccionario de query y diccionario de formato
    """
    # Construir query a partir de parámetros
    query = translate_keys(parsed_params, {
        N.ID: 'street_id',
        N.NAME: 'road_name',
        N.STATE: 'state',
        N.DEPT: 'department',
        N.EXACT: 'exact',
        N.FIELDS: 'fields',
        N.ROAD_TYPE: 'road_type'
    }, ignore=[N.FLATTEN, N.FORMAT])

    query['excludes'] = [N.GEOM]

    # Construir reglas de formato a partir de parámetros
    fmt = {
        key: parsed_params[key]
        for key in [N.FLATTEN, N.FIELDS, N.FORMAT]
        if key in parsed_params
    }
    fmt[N.CSV_FIELDS] = formatter.STREETS_CSV_FIELDS

    return query, fmt


def process_street_single(request):
    """Procesa una request GET para consultar datos de calles.
    En caso de ocurrir un error de parseo, se retorna una respuesta HTTP 400.

    Args:
        request (flask.Request): Request GET de flask.

    Raises:
        data.DataConnectionException: En caso de ocurrir un error de
            conexión con la capa de manejo de datos.

    Returns:
        flask.Response: respuesta HTTP
    """
    try:
        qs_params = params.PARAMS_STREETS.parse_get_params(request.args)
    except params.ParameterParsingException as e:
        return formatter.create_param_error_response_single(e.errors)

    query, fmt = build_street_query_format(qs_params)

    es = get_elasticsearch()
    result = data.search_streets(es, [query])[0]

    source = get_index_source(N.STREETS)
    for match in result:
        match[N.SOURCE] = source

    return formatter.create_ok_response(N.STREETS, result, fmt)


def process_street_bulk(request):
    """Procesa una request POST para consultar datos de calles.
    En caso de ocurrir un error de parseo, se retorna una respuesta HTTP 400.

    Args:
        request (flask.Request): Request POST de flask.

    Raises:
        data.DataConnectionException: En caso de ocurrir un error de
            conexión con la capa de manejo de datos.

    Returns:
        flask.Response: respuesta HTTP
    """
    try:
        body_params = params.PARAMS_STREETS.parse_post_params(
            request.args, request.json and request.json.get(N.STREETS))
    except params.ParameterParsingException as e:
        return formatter.create_param_error_response_bulk(e.errors)

    queries = []
    formats = []
    for parsed_params in body_params:
        query, fmt = build_street_query_format(parsed_params)
        queries.append(query)
        formats.append(fmt)

    es = get_elasticsearch()
    results = data.search_streets(es, queries)

    source = get_index_source(N.STREETS)
    for result in results:
        for match in result:
            match[N.SOURCE] = source

    return formatter.create_ok_response_bulk(N.STREETS, results, formats)


def process_street(request):
    """Procesa una request GET o POST para consultar datos de calles.
    En caso de ocurrir un error de parseo, se retorna una respuesta HTTP 400.
    En caso de ocurrir un error interno, se retorna una respuesta HTTP 500.

    Args:
        request (flask.Request): Request GET o POST de flask.

    Returns:
        flask.Response: respuesta HTTP
    """
    try:
        if request.method == 'GET':
            return process_street_single(request)
        else:
            return process_street_bulk(request)
    except data.DataConnectionException:
        return formatter.create_internal_error_response()


def build_addresses_result(result, query, source):
    """Construye resultados para una consulta al endpoint de direcciones.
    Modifica los resultados contenidos en la lista 'result', agregando
    ubicación, altura y nomenclatura con altura.

    Args:
        result (list): Resultados de una búsqueda al índice de calles.
            (lista de calles).
        query (dict): Query utilizada para obtener los resultados.
        source (str): Nombre de la fuente de los datos.

    """
    fields = query['fields']
    number = query['number']
    pool = get_postgres_db_connection_pool()

    with get_postgres_db_connection(pool) as connection:
        for street in result:
            if N.FULL_NAME in fields:
                parts = street[N.FULL_NAME].split(',')
                parts[0] += ' {}'.format(number)
                street[N.FULL_NAME] = ','.join(parts)

            door_nums = street.pop(N.DOOR_NUM)
            start_r = door_nums[N.START][N.RIGHT]
            end_l = door_nums[N.END][N.LEFT]
            geom = street.pop(N.GEOM)

            if N.DOOR_NUM in fields:
                street[N.DOOR_NUM] = number

            if N.LOCATION_LAT in fields or N.LOCATION_LON in fields:
                loc = data.street_number_location(connection, geom, number,
                                                  start_r, end_l)
                street[N.LOCATION] = loc

            street[N.SOURCE] = source


def build_address_query_format(parsed_params):
    """Construye dos diccionarios a partir de parámetros de consulta
    recibidos, el primero representando la query a Elasticsearch a
    realizar y el segundo representando las propiedades de formato
    (presentación) que se le debe dar a los datos obtenidos de la misma.

    Args:
        parsed_params (dict): Parámetros de una consulta normalización de
            una dirección.

    Returns:
        tuple: diccionario de query y diccionario de formato
    """
    # Construir query a partir de parámetros
    road_name, number = parsed_params.pop(N.ADDRESS)
    parsed_params['road_name'] = road_name
    parsed_params['number'] = number

    query = translate_keys(parsed_params, {
        N.DEPT: 'department',
        N.STATE: 'state',
        N.EXACT: 'exact',
        N.ROAD_TYPE: 'road_type'
    }, ignore=[N.FLATTEN, N.FORMAT, N.FIELDS])

    query['fields'] = parsed_params[N.FIELDS] + [N.GEOM, N.START_R, N.END_L]
    query['excludes'] = [N.START_L, N.END_R]

    # Construir reglas de formato a partir de parámetros
    fmt = {
        key: parsed_params[key]
        for key in [N.FLATTEN, N.FIELDS, N.FORMAT]
        if key in parsed_params
    }
    fmt[N.CSV_FIELDS] = formatter.ADDRESSES_CSV_FIELDS

    return query, fmt


def process_address_single(request):
    """Procesa una request GET para normalizar una dirección.
    En caso de ocurrir un error de parseo, se retorna una respuesta HTTP 400.

    Args:
        request (flask.Request): Request GET de flask.

    Raises:
        data.DataConnectionException: En caso de ocurrir un error de
            conexión con la capa de manejo de datos.

    Returns:
        flask.Response: respuesta HTTP
    """
    try:
        qs_params = params.PARAMS_ADDRESSES.parse_get_params(request.args)
    except params.ParameterParsingException as e:
        return formatter.create_param_error_response_single(e.errors)

    query, fmt = build_address_query_format(qs_params)

    es = get_elasticsearch()
    result = data.search_streets(es, [query])[0]

    source = get_index_source(N.STREETS)
    build_addresses_result(result, query, source)

    return formatter.create_ok_response(N.ADDRESSES, result, fmt)


def process_address_bulk(request):
    """Procesa una request POST para normalizar lote de direcciones.
    En caso de ocurrir un error de parseo, se retorna una respuesta HTTP 400.

    Args:
        request (flask.Request): Request POST de flask.

    Raises:
        data.DataConnectionException: En caso de ocurrir un error de
            conexión con la capa de manejo de datos.

    Returns:
        flask.Response: respuesta HTTP
    """
    try:
        body_params = params.PARAMS_ADDRESSES.parse_post_params(
            request.args, request.json and request.json.get(N.ADDRESSES))
    except params.ParameterParsingException as e:
        return formatter.create_param_error_response_bulk(e.errors)

    queries = []
    formats = []
    for parsed_params in body_params:
        query, fmt = build_address_query_format(parsed_params)
        queries.append(query)
        formats.append(fmt)

    es = get_elasticsearch()
    results = data.search_streets(es, queries)

    source = get_index_source(N.STREETS)
    for result, query in zip(results, queries):
        build_addresses_result(result, query, source)

    return formatter.create_ok_response_bulk(N.ADDRESSES, results, formats)


def process_address(request):
    """Procesa una request GET o POST para normalizar lote de direcciones.
    En caso de ocurrir un error de parseo, se retorna una respuesta HTTP 400.
    En caso de ocurrir un error interno, se retorna una respuesta HTTP 500.

    Args:
        request (flask.Request): Request GET o POST de flask.

    Returns:
        flask.Response: respuesta HTTP

    """
    try:
        if request.method == 'GET':
            return process_address_single(request)
        else:
            return process_address_bulk(request)
    except data.DataConnectionException:
        return formatter.create_internal_error_response()


def build_place_result(query, dept, muni):
    """Construye un resultado para una consulta al endpoint de ubicación.

    Args:
        query (dict): Query utilizada para obtener los resultados.
        dept (dict): Departamento encontrado en la ubicación especificada.
            Puede ser None.
        muni (dict): Municipio encontrado en la ubicación especificada. Puede
            ser None.

    Returns:
        dict: Resultado de ubicación con los campos apropiados

    """
    empty_entity = {
        N.ID: None,
        N.NAME: None
    }

    if not dept:
        state = empty_entity.copy()
        dept = empty_entity.copy()
        muni = empty_entity.copy()
        source = None
    else:
        # Remover la provincia del departamento y colocarla directamente
        # en el resultado. Haciendo esto se logra evitar una consulta
        # al índice de provincias.
        state = dept.pop(N.STATE)
        muni = muni or empty_entity.copy()
        source = get_index_source(N.DEPARTMENTS)

    place = {
        N.STATE: state,
        N.DEPT: dept,
        N.MUN: muni,
        N.LAT: query['lat'],
        N.LON: query['lon'],
        N.SOURCE: source
    }

    return place


def build_place_query_format(parsed_params):
    """Construye dos diccionarios a partir de parámetros de consulta
    recibidos, el primero representando la query a Elasticsearch a
    realizar y el segundo representando las propiedades de formato
    (presentación) que se le debe dar a los datos obtenidos de la misma.

    Args:
        parsed_params (dict): Parámetros de una consulta para una ubicación.

    Returns:
        tuple: diccionario de query y diccionario de formato
    """
    # Construir query a partir de parámetros
    query = translate_keys(parsed_params, {}, ignore=[N.FLATTEN, N.FORMAT])

    # Construir reglas de formato a partir de parámetros
    fmt = {
        key: parsed_params[key]
        for key in [N.FLATTEN, N.FIELDS, N.FORMAT]
        if key in parsed_params
    }

    return query, fmt


def process_place_queries(es, queries):
    """Dada una lista de queries de ubicación, construye las queries apropiadas
    a índices de departamentos y municipios, y las ejecuta utilizando
    Elasticsearch.

    Args:
        es (Elasticsearch): Conexión a Elasticsearch.
        queries (list): Lista de queries de ubicación

    Returns:
        list: Resultados de ubicaciones con los campos apropiados

    """
    dept_queries = []
    for query in queries:
        dept_queries.append({
            'lat': query['lat'],
            'lon': query['lon'],
            'fields': [N.ID, N.NAME, N.STATE]
        })

    departments = data.search_places(es, N.DEPARTMENTS, dept_queries)

    muni_queries = []
    for query in queries:
        muni_queries.append({
            'lat': query['lat'],
            'lon': query['lon'],
            'fields': [N.ID, N.NAME]
        })

    munis = data.search_places(es, N.MUNICIPALITIES, muni_queries)

    places = []
    for query, dept, muni in zip(queries, departments, munis):
        places.append(build_place_result(query, dept, muni))

    return places


def process_place_single(request):
    """Procesa una request GET para obtener entidades en un punto.
    En caso de ocurrir un error de parseo, se retorna una respuesta HTTP 400.

    Args:
        request (flask.Request): Request GET de flask.

    Raises:
        data.DataConnectionException: En caso de ocurrir un error de
            conexión con la capa de manejo de datos.

    Returns:
        flask.Response: respuesta HTTP
    """
    try:
        qs_params = params.PARAMS_PLACE.parse_get_params(request.args)
    except params.ParameterParsingException as e:
        return formatter.create_param_error_response_single(e.errors)

    query, fmt = build_place_query_format(qs_params)

    es = get_elasticsearch()
    result = process_place_queries(es, [query])[0]

    return formatter.create_ok_response(N.PLACE, result, fmt,
                                        iterable_result=False)


def process_place_bulk(request):
    """Procesa una request POST para obtener entidades en varios puntos.
    En caso de ocurrir un error de parseo, se retorna una respuesta HTTP 400.

    Args:
        request (flask.Request): Request POST de flask.

    Raises:
        data.DataConnectionException: En caso de ocurrir un error de
            conexión con la capa de manejo de datos.

    Returns:
        flask.Response: respuesta HTTP
    """
    try:
        body_params = params.PARAMS_PLACE.parse_post_params(
            request.args, request.json and request.json.get(N.PLACES))
    except params.ParameterParsingException as e:
        return formatter.create_param_error_response_bulk(e.errors)

    queries = []
    formats = []
    for parsed_params in body_params:
        query, fmt = build_place_query_format(parsed_params)
        queries.append(query)
        formats.append(fmt)

    es = get_elasticsearch()
    results = process_place_queries(es, queries)

    return formatter.create_ok_response_bulk(N.PLACE, results, formats,
                                             iterable_result=False)


def process_place(request):
    """Procesa una request GET o POST para obtener entidades en una o varias
    ubicaciones.
    En caso de ocurrir un error de parseo, se retorna una respuesta HTTP 400.
    En caso de ocurrir un error interno, se retorna una respuesta HTTP 500.

    Args:
        request (flask.Request): Request GET o POST de flask.

    Returns:
        flask.Response: respuesta HTTP

    """
    try:
        if request.method == 'GET':
            return process_place_single(request)
        else:
            return process_place_bulk(request)
    except data.DataConnectionException:
        return formatter.create_internal_error_response()
