"""Módulo 'params' de georef-api

Contiene clases utilizadas para leer y validar parámetros recibidos en requests
HTTP.
"""

import service.names as N
from service import strings

import re
from enum import Enum, unique
from collections import namedtuple

MAX_BULK_LEN = 5000
MAX_SIZE_LEN = MAX_BULK_LEN


class ParameterParsingException(Exception):
    def __init__(self, errors):
        self._errors = errors

    @property
    def errors(self):
        return self._errors

    """Excepción lanzada al finalizar la recolección de errores para todos los
    parámetros.

    """

    pass


class ParameterRequiredException(Exception):
    """Excepción lanzada cuando se detecta la ausencia de un parámetro
    requerido.

    """

    pass


class InvalidChoiceException(Exception):
    """Excepción lanzada cuando un parámetro no tiene como valor uno de los
    valores permitidos.

    """

    pass


@unique
class ParamErrorType(Enum):
    """Códigos de error para cada tipo de error de parámetro.

    Nota: En caso de agregar un nuevo error, no reemplazar un valor existente,
    crear uno nuevo.

    """

    UNKNOWN_PARAM = 1000
    VALUE_ERROR = 1001
    INVALID_CHOICE = 1002
    PARAM_REQUIRED = 1003
    INVALID_BULK = 1004
    INVALID_LOCATION = 1005
    REPEATED = 1006
    INVALID_BULK_ENTRY = 1007
    INVALID_BULK_LEN = 1008
    INVALID_SET = 1009


ParamError = namedtuple('ParamError', ['error_type', 'message', 'source'])
"""La clase ParamError representa toda la información conocida sobre un error
de parámetro.
"""


class Parameter:
    """Representa un parámetro cuyo valor es recibido a través de una request
    HTTP.

    La clase se encarga de validar el valor recibido vía HTTP (en forma de
    string), comprobando también que el valor haya sido recibido (en caso de
    ser un parámetro requerido).

    Attributes:
        choices (list): Lista de valores permitidos (o None si se permite
            cualquier valor).
        required (bool): Verdadero si el parámetro es requerido.
        default: Valor que debería tomar el parámetro en caso de no haber sido
            recibido.

    """

    def __init__(self, required=False, default=None, choices=None):
        """Inicializa un objeto Parameter.

        Args:
            choices (list): Lista de valores permitidos (o None si se permite
                cualquier valor).
            required (bool): Verdadero si el parámetro es requerido.
            default: Valor que debería tomar el parámetro en caso de no haber
                sido recibido.

        """
        if required and default is not None:
            raise ValueError(strings.OBLIGATORY_NO_DEFAULT)

        self._choices = choices
        self._required = required
        self._default = default

        if choices and \
           default is not None \
           and not self._value_in_choices(default):
            raise ValueError(strings.DEFAULT_INVALID_CHOICE)

    def get_value(self, val):
        """Toma un valor 'val' recibido desde una request HTTP, y devuelve el
        verdadero valor (con tipo apropiado) resultante de acuerdo a las
        propiedades del objeto Parameter.

        Args:
            val (str): String recibido desde la request HTTP, o None si no se
                recibió un valor.
            from_source (str): Ubicación de la request HTTP donde se recibió el
                valor.

        Returns:
            El valor del parámetro resultante, cuyo tipo depende de las reglas
            definidas por el objeto Parameter y sus subclases.

        """
        if val is None:
            if self._required:
                raise ParameterRequiredException()
            else:
                return self._default

        parsed = self._parse_value(val)

        if self._choices and not self._value_in_choices(parsed):
            raise InvalidChoiceException(
                strings.INVALID_CHOICE.format(', '.join(self._choices)))

        return parsed

    def validate_values(self, vals):
        """Comprueba que una serie de valores (ya con los tipos apropiados)
        sean válidos como conjunto. Este método se utiliza durante el parseo
        del body en requests POST, para validar uno o más valores como
        conjunto. Por ejemplo, el parámetro 'max' establece que la suma de
        todos los parámetros max recibidos no pueden estar por debajo o por
        encima de ciertos valores.

        Args:
            vals (list): Lista de valores a validar en conjunto.

        Raises:
            ValueError: Si la validación no fue exitosa.

        """
        # Por default, un parámetro no realiza validaciones a nivel conjunto
        # de valores.
        pass

    def _value_in_choices(self, val):
        """Comprueba que un valor esté dentro de los valores permitidos del
        objeto Parameter. El valor ya debería estar parseado y tener el tipo
        apropiado.

        Args:
            val: Valor a comprobar si está contenido dentro de los valores
                permitidos.

        Returns:
            bool: Verdadero si el valor está contenido dentro de los valores
                permitidos

        """
        return val in self._choices

    def _parse_value(self, val):
        """Parsea un valor de tipo string y devuelve el resultado con el tipo
        apropiado.

        Args:
            val (str): Valor a parsear.

        Returns:
            El valor parseado.

        """
        raise NotImplementedError()


class StrParameter(Parameter):
    """Representa un parámetro de tipo string no vacío.

    Se heredan las propiedades y métodos de la clase Parameter, definiendo
    nuevamente el método '_parse_value' para implementar lógica de parseo y
    validación propias de StrParameter.

    """

    def _parse_value(self, val):
        if not val:
            raise ValueError(strings.STRING_EMPTY)

        return val


class IdParameter(Parameter):
    """Representa un parámetro de tipo ID numérico.

    Se heredan las propiedades y métodos de la clase Parameter, definiendo
    nuevamente el método '_parse_value' para implementar lógica de parseo y
    validación propias de IdParameter.

    """
    def __init__(self, length, padding_char='0', padding_length=1):
        self._length = length
        self._padding_char = padding_char
        self._min_length = length - padding_length
        super().__init__()

    def _parse_value(self, val):
        if not val.isdigit() or \
           len(val) > self._length or \
           len(val) < self._min_length:
            raise ValueError(strings.ID_PARAM_INVALID.format(self._length))

        return val.rjust(self._length, self._padding_char)


class StrOrIdParameter(Parameter):
    """Representa un parámetro de tipo string no vacío, o un ID numérico.

    Se heredan las propiedades y métodos de la clase Parameter, definiendo
    nuevamente el método '_parse_value' para implementar lógica de parseo y
    validación propias de StrOrIdParameter.

    """
    def __init__(self, id_length, id_padding_char='0'):
        self._id_param = IdParameter(id_length, id_padding_char)
        self._str_param = StrParameter()
        super().__init__()

    def _parse_value(self, val):
        if val.isdigit():
            return self._id_param._parse_value(val)
        else:
            return self._str_param._parse_value(val)


class BoolParameter(Parameter):
    """Representa un parámetro de tipo booleano.

    Se heredan las propiedades y métodos de la clase Parameter, definiendo
    nuevamente el método '_parse_value' para implementar lógica de parseo y
    validación propias de BoolParameter.

    """

    def __init__(self):
        super().__init__(False, False, [True, False])

    def _parse_value(self, val):
        # Cualquier valor recibido (no nulo) es verdadero
        return val is not None


class StrListParameter(Parameter):
    """Representa un parámetro de tipo lista de strings.

    Se heredan las propiedades y métodos de la clase Parameter, definiendo
    nuevamente el método '_parse_value' para implementar lógica de parseo y
    validación propias de StrListParameter. Se define también el método
    _value_in_choices para modificar su comportamiento original.

    """

    def __init__(self, required=False, constants=None, optionals=None):
        self._constants = set(constants) if constants else set()
        optionals = set(optionals) if optionals else set()
        all_values = self._constants | optionals

        super().__init__(required, list(all_values), all_values)

    def _value_in_choices(self, val):
        # La variable val es de tipo set o list, self._choices es de tipo set:
        # devolver falso si existen elementos en val que no están en
        # self._choices.
        return not (set(val) - self._choices)

    def _parse_value(self, val):
        if not val:
            raise ValueError(strings.STRLIST_EMPTY)

        parts = val.split(',')
        received = set(part.strip() for part in parts)
        if len(parts) != len(received):
            raise ValueError(strings.STRLIST_REPEATED)

        # Siempre se agregan los valores constantes
        return list(self._constants | received)


class IntParameter(Parameter):
    """Representa un parámetro de tipo entero.

    Se heredan las propiedades y métodos de la clase Parameter, definiendo
    nuevamente el método '_parse_value' para implementar lógica de parseo y
    validación propias de IntParameter, y 'valid_values' para validar uno
    o más parámetros 'max' recibidos en conjunto.

    """
    def __init__(self, required=False, default=None, choices=None,
                 lower_limit=None, upper_limit=None):
        self._lower_limit = lower_limit
        self._upper_limit = upper_limit
        super().__init__(required, default, choices)

    def _parse_value(self, val):
        try:
            int_val = int(val)
        except ValueError:
            raise ValueError(strings.INT_VAL_ERROR)

        if self._lower_limit is not None and int_val < self._lower_limit:
            raise ValueError(strings.INT_VAL_SMALL.format(self._lower_limit))

        if self._upper_limit is not None and int_val > self._upper_limit:
            raise ValueError(strings.INT_VAL_BIG.format(self._upper_limit))

        return int_val

    def validate_values(self, vals):
        if sum(vals) > self._upper_limit:
            raise ValueError(
                strings.INT_VAL_BIG_GLOBAL.format(self._upper_limit))


class FloatParameter(Parameter):
    """Representa un parámetro de tipo float.

    Se heredan las propiedades y métodos de la clase Parameter, definiendo
    nuevamente el método '_parse_value' para implementar lógica de parseo y
    validación propias de FloatParameter.

    """

    def _parse_value(self, val):
        try:
            return float(val)
        except ValueError:
            raise ValueError(strings.FLOAT_VAL_ERROR)


class AddressParameter(Parameter):
    """Representa un parámetro de tipo dirección de calle (nombre y altura).

    Se heredan las propiedades y métodos de la clase Parameter, definiendo
    nuevamente el método '_parse_value' para implementar lógica de parseo y
    validación propias de AddressParameter.

    """

    def __init__(self):
        super().__init__(required=True)

    def _parse_value(self, val):
        # 1) Remover ítems entre paréntesis e indicadores de número (N°, n°)
        val = re.sub(r'\(.*?\)|[nN][°º]', '', val.strip())

        parts = [
            # 3) Normalizar espacios
            ' '.join(part.strip().split())
            for part
            # 2) Dividir el texto utilizando guiones, comas e indicadores
            # de barrio (B°, b°)
            in re.split(r'-|,|[bB][°º]', val)
            if part
        ]

        address = None
        for part in parts:
            # 4) Por cada parte de texto resultante, buscar un nombre de calle
            # junto a una altura numérica. La altura debe estar al final del
            # texto. Priorizar los primeros resultados válidos encontrados.
            match = re.search(r'^(.+?)\s+([0-9]+)$', part)
            if match:
                name, num = match.groups()

                if int(num) > 0:
                    address = name, num
                    break

        if not address:
            raise ValueError(strings.ADDRESS_NO_NUM)

        return address


class EndpointParameters():
    """Representa un conjunto de parámetros para un endpoint HTTP.

    Attributes:
        _get_qs_params (dict): Diccionario de parámetros aceptados vía
            querystring en requests GET, siendo las keys los nombres de los
            parámetros que se debe usar al especificarlos, y los valores
            objetos de tipo Parameter.

        _shared_params (dict): Similar a 'get_qs_params', pero contiene
            parámetros aceptados vía querystring en requests GET Y parámetros
            aceptados vía body en requests POST (compartidos).

    """

    def __init__(self, shared_params=None, get_qs_params=None):
        """Inicializa un objeto de tipo EndpointParameters.

        Args:
            get_qs_params (dict): Ver atributo 'get_qs_params'.
            shared_params (dict): Ver atributo 'shared_params'.

        """
        shared_params = shared_params or {}
        get_qs_params = get_qs_params or {}

        self._get_qs_params = {**get_qs_params, **shared_params}
        self._post_body_params = shared_params

    def parse_params_dict(self, params, received, from_source):
        """Parsea parámetros (clave-valor) recibidos en una request HTTP,
        utilizando el conjunto 'params' de parámetros.

        Args:
            params (dict): Diccionario de objetos Parameter (nombre-Parameter).
            received (dict): Parámetros recibidos sin procesar (nombre-valor).
            from_source (str): Ubicación dentro de la request HTTP donde fueron
                recibidos los parámetros.

        Returns:
            list: Lista de resultados. Los resultados consisten de un
                diccionario conteniendo como clave el nombre del parámetro, y
                como valor el valor parseado y validado, con su tipo apropiado.

        Raises:
            ParameterParsingException: Excepción con errores de parseo
                de parámetros.

        """
        parsed, errors = {}, {}
        is_multi_dict = hasattr(received, 'getlist')

        for param_name, param in params.items():
            received_val = received.get(param_name)

            if is_multi_dict and len(received.getlist(param_name)) > 1:
                errors[param_name] = ParamError(ParamErrorType.REPEATED,
                                                strings.REPEATED_ERROR,
                                                from_source)
                continue

            try:
                parsed[param_name] = param.get_value(received_val)
            except ParameterRequiredException:
                errors[param_name] = ParamError(ParamErrorType.PARAM_REQUIRED,
                                                strings.MISSING_ERROR,
                                                from_source)
            except ValueError as e:
                errors[param_name] = ParamError(ParamErrorType.VALUE_ERROR,
                                                str(e), from_source)
            except InvalidChoiceException as e:
                errors[param_name] = ParamError(ParamErrorType.INVALID_CHOICE,
                                                str(e), from_source)

        for param_name in received:
            if param_name not in params:
                errors[param_name] = ParamError(ParamErrorType.UNKNOWN_PARAM,
                                                strings.UNKNOWN_ERROR,
                                                from_source)

        if errors:
            raise ParameterParsingException(errors)

        return parsed

    def parse_post_params(self, qs_params, body_params):
        """Parsea parámetros (clave-valor) recibidos en una request HTTP
        POST utilizando el conjunto de parámetros internos. Se parsean por
        separado los parámetros querystring y los parámetros de body.

        Args:
            qs_params (dict): Parámetros recibidos en el query string.
            body_params (list): Lista de diccionarios, cada uno representando
                un conjunto de parámetros recibidos en el body del request
                HTTP.

        Returns:
            list: lista de conjuntos de parámetros parseados provienentes
                de 'parse_param_dict'.

        Raises:
            ParameterParsingException: Excepción con errores de parseo
                de parámetros.

        """
        if qs_params:
            # No aceptar parámetros de querystring en bulk
            raise ParameterParsingException([
                {'querystring': ParamError(ParamErrorType.INVALID_LOCATION,
                                           strings.BULK_QS_INVALID,
                                           'querystring')}
            ])

        if not body_params or not isinstance(body_params, list):
            # No aceptar operaciones bulk que no sean listas, y no
            # aceptar listas vacías.
            raise ParameterParsingException([
                {'body': ParamError(ParamErrorType.INVALID_BULK,
                                    strings.INVALID_BULK, 'body')}
            ])

        if len(body_params) > MAX_BULK_LEN:
            raise ParameterParsingException([
                {'body': ParamError(
                    ParamErrorType.INVALID_BULK_LEN,
                    strings.BULK_LEN_ERROR.format(MAX_BULK_LEN), 'body')}
            ])

        results, errors_list = [], []
        for param_dict in body_params:
            parsed, errors = {}, {}
            if not hasattr(param_dict, 'get'):
                errors['body'] = ParamError(ParamErrorType.INVALID_BULK_ENTRY,
                                            strings.INVALID_BULK_ENTRY, 'body')
            else:
                try:
                    parsed = self.parse_params_dict(self._post_body_params,
                                                    param_dict, 'body')
                except ParameterParsingException as e:
                    errors = e.errors

            results.append(parsed)
            errors_list.append(errors)

        if any(errors_list):
            raise ParameterParsingException(errors_list)

        for name, param in self._post_body_params.items():
            try:
                # Validar conjuntos de valores de parámetros bajo el
                # mismo nombre
                param.validate_values(result[name] for result in results)
            except ValueError as e:
                error = ParamError(ParamErrorType.INVALID_SET, str(e),
                                   'body')

                # Si la validación no fue exitosa, crear un error y
                # agregarlo al conjunto de errores de cada consulta que lo
                # utilizó.
                for errors in errors_list:
                    errors[name] = error

        # Luego de validar conjuntos, lanzar una excepción si se generaron
        # errores nuevos
        if any(errors_list):
            raise ParameterParsingException(errors_list)

        return results

    def parse_get_params(self, qs_params):
        """Parsea parámetros (clave-valor) recibidos en una request HTTP GET
        utilizando el conjunto de parámetros internos.

        Args:
            qs_params (dict): Parámetros recibidos en el query string.

        Returns:
            list: Valor de retorno de 'parse_dict_params'.

        Raises:
            ParameterParsingException: Excepción con errores de parseo
                de parámetros.

        """
        return self.parse_params_dict(self._get_qs_params, qs_params,
                                      'querystring')


PARAMS_STATES = EndpointParameters(shared_params={
    N.ID: IdParameter(length=2),
    N.NAME: StrParameter(),
    N.ORDER: StrParameter(choices=[N.ID, N.NAME]),
    N.FLATTEN: BoolParameter(),
    N.FIELDS: StrListParameter(constants=[N.ID, N.NAME, N.SOURCE],
                               optionals=[N.C_LAT, N.C_LON]),
    N.MAX: IntParameter(default=24, lower_limit=1, upper_limit=MAX_SIZE_LEN),
    N.EXACT: BoolParameter()
}, get_qs_params={
    N.FORMAT: StrParameter(default='json', choices=['json', 'csv', 'geojson'])
})

PARAMS_DEPARTMENTS = EndpointParameters(shared_params={
    N.ID: IdParameter(length=5),
    N.NAME: StrParameter(),
    N.STATE: StrOrIdParameter(id_length=2),
    N.ORDER: StrParameter(choices=[N.ID, N.NAME]),
    N.FLATTEN: BoolParameter(),
    N.FIELDS: StrListParameter(constants=[N.ID, N.NAME, N.SOURCE],
                               optionals=[N.C_LAT, N.C_LON, N.STATE_ID,
                                          N.STATE_NAME]),
    N.MAX: IntParameter(default=10, lower_limit=1, upper_limit=MAX_SIZE_LEN),
    N.EXACT: BoolParameter()
}, get_qs_params={
    N.FORMAT: StrParameter(default='json', choices=['json', 'csv', 'geojson'])
})

PARAMS_MUNICIPALITIES = EndpointParameters(shared_params={
    N.ID: IdParameter(length=6),
    N.NAME: StrParameter(),
    N.STATE: StrOrIdParameter(id_length=2),
    N.DEPT: StrOrIdParameter(id_length=5),
    N.ORDER: StrParameter(choices=[N.ID, N.NAME]),
    N.FLATTEN: BoolParameter(),
    N.FIELDS: StrListParameter(constants=[N.ID, N.NAME, N.SOURCE],
                               optionals=[N.C_LAT, N.C_LON, N.STATE_ID,
                                          N.STATE_NAME, N.DEPT_ID,
                                          N.DEPT_NAME]),
    N.MAX: IntParameter(default=10, lower_limit=1, upper_limit=MAX_SIZE_LEN),
    N.EXACT: BoolParameter()
}, get_qs_params={
    N.FORMAT: StrParameter(default='json', choices=['json', 'csv', 'geojson'])
})

PARAMS_LOCALITIES = EndpointParameters(shared_params={
    N.ID: IdParameter(length=11),
    N.NAME: StrParameter(),
    N.STATE: StrOrIdParameter(id_length=2),
    N.DEPT: StrOrIdParameter(id_length=5),
    N.MUN: StrOrIdParameter(id_length=6),
    N.ORDER: StrParameter(choices=[N.ID, N.NAME]),
    N.FLATTEN: BoolParameter(),
    N.FIELDS: StrListParameter(constants=[N.ID, N.NAME, N.SOURCE],
                               optionals=[N.C_LAT, N.C_LON, N.STATE_ID,
                                          N.STATE_NAME, N.DEPT_ID, N.DEPT_NAME,
                                          N.MUN_ID, N.MUN_NAME,
                                          N.LOCALITY_TYPE]),
    N.MAX: IntParameter(default=10, lower_limit=1, upper_limit=MAX_SIZE_LEN),
    N.EXACT: BoolParameter()
}, get_qs_params={
    N.FORMAT: StrParameter(default='json', choices=['json', 'csv', 'geojson'])
})

PARAMS_ADDRESSES = EndpointParameters(shared_params={
    N.ADDRESS: AddressParameter(),
    N.ROAD_TYPE: StrParameter(),
    N.STATE: StrOrIdParameter(id_length=2),
    N.DEPT: StrOrIdParameter(id_length=5),
    N.FLATTEN: BoolParameter(),
    N.FIELDS: StrListParameter(constants=[N.ID, N.NAME, N.DOOR_NUM,
                                          N.SOURCE],
                               optionals=[N.STATE_ID, N.STATE_NAME, N.DEPT_ID,
                                          N.DEPT_NAME, N.ROAD_TYPE,
                                          N.FULL_NAME, N.LOCATION_LAT,
                                          N.LOCATION_LON]),
    N.MAX: IntParameter(default=10, lower_limit=1, upper_limit=MAX_SIZE_LEN),
    N.EXACT: BoolParameter()
}, get_qs_params={
    N.FORMAT: StrParameter(default='json', choices=['json', 'csv'])
})

PARAMS_STREETS = EndpointParameters(shared_params={
    N.ID: IdParameter(length=13),
    N.NAME: StrParameter(),
    N.ROAD_TYPE: StrParameter(),
    N.STATE: StrOrIdParameter(id_length=2),
    N.DEPT: StrOrIdParameter(id_length=5),
    N.FLATTEN: BoolParameter(),
    N.FIELDS: StrListParameter(constants=[N.ID, N.NAME, N.SOURCE],
                               optionals=[N.START_R, N.START_L, N.END_R,
                                          N.END_L, N.STATE_ID, N.STATE_NAME,
                                          N.DEPT_ID, N.DEPT_NAME, N.FULL_NAME,
                                          N.ROAD_TYPE]),
    N.MAX: IntParameter(default=10, lower_limit=1, upper_limit=MAX_SIZE_LEN),
    N.EXACT: BoolParameter()
}, get_qs_params={
    N.FORMAT: StrParameter(default='json', choices=['json', 'csv'])
})

PARAMS_PLACE = EndpointParameters(shared_params={
    N.LAT: FloatParameter(required=True),
    N.LON: FloatParameter(required=True),
    N.FLATTEN: BoolParameter(),
    N.FIELDS: StrListParameter(constants=[N.STATE_ID, N.STATE_NAME, N.SOURCE],
                               optionals=[N.DEPT_ID, N.DEPT_NAME, N.MUN_ID,
                                          N.MUN_NAME, N.LAT, N.LON])
}, get_qs_params={
    N.FORMAT: StrParameter(default='json', choices=['json', 'geojson'])
})
