from __future__ import annotations

import collections.abc as abc
import dataclasses as dc
import datetime as dt
import enum as enum
import typing as tp
import xml.etree.ElementTree as pyet
from warnings import deprecated, warn

import lxml.etree as lxet


def _make_xml_attrs(obj: object, add_extra: bool = False, **kwargs) -> dict[str, str]:
  if not dc.is_dataclass(obj):
    raise TypeError(f"Expected a dataclass but got {type(obj)!r}")
  xml_attrs: dict[str, str] = dict()
  for field in dc.fields(obj):
    type_: tp.Type
    if "int" in field.type:
      type_ = int
    elif "SEGTYPE" in field.type:
      type_ = enum.Enum
    elif "ASSOC" in field.type:
      type_ = enum.Enum
    elif "POS" in field.type:
      type_ = enum.Enum
    elif "dt" in field.type:
      type_ = dt.datetime
    else:
      type_ = str
    if not field.metadata.get("exclude", False):
      val = kwargs.pop(field.name, getattr(obj, field.name))
      if val is None and field.default is not dc.MISSING:
        continue
      if not isinstance(val, type_):
        raise TypeError(f"Expected {type_!r} for {field.name!r} but got {type(val)!r}")
      if isinstance(val, int):
        val = str(val)
      elif isinstance(val, enum.Enum):
        val = val.value
      elif isinstance(val, dt.datetime):
        val = val.strftime("%Y%m%dT%H%M%SZ")
      elif isinstance(val, str):
        pass
      xml_attrs[field.metadata.get("export_name", field.name)] = val
  if add_extra:
    xml_attrs.update(kwargs)
  return xml_attrs


@tp.overload
def _make_elem(
  tag: str, attrib: dict[str, str], engine: tp.Literal[ENGINE.LXML]
) -> lxet._Element: ...
@tp.overload
def _make_elem(
  tag: str, attrib: dict[str, str], engine: tp.Literal[ENGINE.PYTHON]
) -> pyet.Element: ...
def _make_elem(
  tag: str, attrib: dict[str, str], engine: tp.Literal[ENGINE.LXML, ENGINE.PYTHON]
) -> lxet._Element | pyet.Element:
  if engine is ENGINE.LXML:
    return lxet.Element(tag, attrib=attrib)
  elif engine is ENGINE.PYTHON:
    return pyet.Element(tag, attrib=attrib)
  else:
    raise ValueError(f"Unknown engine: {engine!r}")


class ENGINE(enum.Enum):
  """
  An Enum that represents which xml engines are available to convert an object
  to a xml element.
  """

  LXML = enum.auto()
  """
  The lxml library, which is faster than the standard library's xml module but
  requires the lxml package to be installed.
  """
  PYTHON = enum.auto()
  """
  The standard library's xml module, which is slower than lxml but doesn't
  require any extra dependencies.
  """


class POS(enum.Enum):
  """
  An Enum representing the possible values for the pos attribute in a <it> tag
  and the It object. Indicates whether the element is a beginning or ending tag.
  """

  BEGIN = "begin"
  """
  This isolated tag is a beginning tag.
  """
  END = "end"
  """
  This isolated tag is an eding tag.
  """


class ASSOC(enum.Enum):
  """
  An Enum representing the possible values for the assoc attribute in a <ph> tag
  and the Ph object. Indicates the element is associated with the text prior or
  after.
  """

  P = "p"
  """
  The element is associated with the text preceding the element.
  """
  F = "f"
  """
  The element is associated with the text following the element.
  """
  B = "b"
  """
  The element is associated with the text on both sides.
  """


class SEGTYPE(enum.Enum):
  """
  An Enum representing the possible values for the segtype attribute. Can be
  used in a <tu> or a <header> tag and their correpsonding element. Specifies
  the kind of segmentation. If a <tu> doesn't specify its segtype, CAT tools
  will default to the one in the <header> tag.
  """

  BLOCK = "block"
  """
  Used when the segment does not correspond to one of the other values, for
  example when you want to store a chapter composed of several paragraphs in a
  single <tu>.
  """
  PARAGRAPH = "paragraph"
  """
  Used when the segment corresponds to a paragraph, i.e. multiple full sentences
  in a single <tu>.
  """
  SENTENCE = "sentence"
  """
  Used when a segment corresponds to a single grammatically correct sentence.
  """
  PHRASE = "phrase"
  """
  Used when a segment corresponds to a single phrase, i.e. a group of words that
  might or might not have semantic meaning.
  """


def _parse_content(
  element: pyet.Element | lxet._Element,
) -> list[str | Ph | It | Hi | Bpt | Ept | Sub | Ut]:
  """
  Internal function to parse the content of an inline tag.

  Returns a list of the content of the tag (usually a <seg>) as a list of strings
  and inline elements in document order.
  If the element has text, it is appended to the list first, then each child is
  parsed and appended to the list, followed by its tail text if it exists.

  The function is Recursive and will go down as far as it needs to parse all the
  content of the element.

  Parameters
  ----------
  element : :external:py:class:`~lxml.etree._Element` | :py:class:`~xml.etree.ElementTree.Element`
      The element to parse.

  Returns
  -------
  list[str | Ph | It | Hi | Bpt | Ept | Sub | Ut]
      A list of strings and inline element parsed from the element as they
      would appear in a CAT tool.

  Raises
  ------
  ValueError
      if the tag is not recognized as an inline tag.
  """
  content: list[str | Ph | It | Hi | Bpt | Ept | Sub | Ut] = []
  if element.text:
    content.append(element.text)
  for child in element:
    match child.tag:
      case "bpt":
        content.append(Bpt.from_element(child))
      case "ept":
        content.append(Ept.from_element(child))
      case "it":
        content.append(It.from_element(child))
      case "hi":
        content.append(Hi.from_element(child))
      case "ph":
        content.append(Ph.from_element(child))
      case "sub":
        content.append(Sub.from_element(child))
      case "ut":
        content.append(Ut.from_element(child))
      case _:
        raise ValueError(f"Unknown tag: {child.tag!r}")
    if child.tail:
      content.append(child.tail)
  return content


def _add_content(
  elem: lxet._Element | pyet.Element,
  content: abc.Sequence[str | Ph | It | Hi | Bpt | Ept | Sub | Ut],
  engine: ENGINE,
  allowed_types: tuple[tp.Type, ...],
) -> None:
  """
  Internal function to add the content of an InlineElement to its XML
  representation using the given engine.

  The function will iterate over the content list and add each item to the element.

  Strings are added first to the element's text attribute. Elements are added
  as children of the element. If there is another string after an element has
  been added, that string is then added to the previous element's tail attribute.

  Parameters
  ----------
  elem : :external:py:class:`~lxml.etree._Element` | :py:class:`~xml.etree.ElementTree.Element`
      The XML element to add content to.
  content : list[str  |  Ph  |  It  |  Hi  |  Bpt  |  Ept  |  Sub  |  Ut]
      The content to be added to the element. A list of InlineElements and strings.
  engine : ENGINE
      The engine used to convert content elements to XML elements.
  allowed_types : tuple[Type, ...]
      A tuple of allowed types for the content elements.

  Raises
  ------
  TypeError
      If an item in the content list is not a string or one of the allowed types.
  """
  last: pyet.Element | lxet._Element = elem
  for item in content:
    if isinstance(item, str):
      if last is elem:
        if elem.text:
          elem.text += item
        else:
          elem.text = item
      else:
        if last.tail:
          last.tail += item
        else:
          last.tail = item
    elif not isinstance(item, allowed_types):
      raise TypeError(
        f"Expected a str or one of {allowed_types!r} element but got {type(item)!r}"
      )
    else:
      last = item.to_element(engine)
      elem.append(last)  # type: ignore


def _parse_notes(elem: pyet.Element | lxet._Element) -> list[Note]:
  """
  Internal function to parse all the notes from the element. Converts them to
  Note objects on the fly.

  Parameters
  ----------
  elem : :external:py:class:`~lxml.etree._Element` | :py:class:`~xml.etree.ElementTree.Element`
      The element to extract notes from.

  Returns
  -------
  list[Note]
      A list of Note object parsed from the object. Returns an empty list if no
      notes are found.
  """
  return [Note.from_element(note) for note in elem.iter("note")]


def _parse_props(elem: pyet.Element | lxet._Element) -> list[Prop]:
  """
  Internal function to parse all the props from the element. Converts them to
  Prop objects on the fly.

  Parameters
  ----------
  elem : :external:py:class:`~lxml.etree._Element` | :py:class:`~xml.etree.ElementTree.Element`
      The element to extract props from.

  Returns
  -------
  list[Prop]
      A list of Prop object parsed from the object. Returns an empty list if no
      props are found.
  """
  return [Prop.from_element(note) for note in elem.iter("prop")]


def _parse_tuvs(elem: pyet.Element | lxet._Element) -> list[Tuv]:
  """
  Internal function to parse all the tuvs from the element. Converts them to
  Tu objects on the fly.

  Parameters
  ----------
  elem : :external:py:class:`~lxml.etree._Element` | :py:class:`~xml.etree.ElementTree.Element`
      The element to extract tuvs from.

  Returns
  -------
  list[Tuv]
      A list of Tu object parsed from the object. Returns an empty list if no
      tuvs are found.
  """
  return [Tuv.from_element(note) for note in elem.iter("tuv")]


def _parse_tus(elem: pyet.Element | lxet._Element) -> list[Tu]:
  """
  Internal function to parse all the tus from the element. Converts them to
  Tuv objects on the fly.

  Parameters
  ----------
  elem : :external:py:class:`~lxml.etree._Element` | :py:class:`~xml.etree.ElementTree.Element`
      The element to extract tus from.

  Returns
  -------
  list[Tu]
      A list of Tu object parsed from the object. Returns an empty list if no
      tuvs are found.
  """
  return [Tu.from_element(note) for note in elem.iter("tu")]


@dc.dataclass(
  kw_only=True,
  slots=True,
  unsafe_hash=True,
)
class Map:
  """
  A dataclass representing a <map/> element in a tmx file.

  The <map/> element is used to specify a user-defined character and some of its
  properties.
  """

  unicode: str = dc.field(
    hash=True,
    compare=True,
  )
  """
  A valid Unicode value (including values in the Private Use areas) in
  hexadecimal format. For example: unicode="#xF8FF". Required."""
  code: tp.Optional[str] = dc.field(
    default=None,
    hash=True,
    compare=True,
  )
  """
  The code-point value corresponding to the unicode character. A hexadecimal
  value prefixed with "#x". For example: code="#x9F". Optional, by default None.
  """
  ent: tp.Optional[str] = dc.field(
    default=None,
    hash=True,
    compare=True,
  )
  """
  The entity name corresponding to the unicode character. Text in ASCII.
  For example: ent="copy". Optional, by default None."""
  subst: tp.Optional[str] = dc.field(
    default=None,
    hash=True,
    compare=True,
  )
  """
  An alternative string for the character.Text in ASCII. For example: subst="(c)"
  for the copyright sign. Optional, by default None."""

  @classmethod
  def from_element(cls, element: pyet.Element | lxet._Element, **kwargs) -> Map:
    """
    Create a Map object from an xml <map/> element.

    Parameters
    ----------
    element : :external:py:class:`~lxml.etree._Element` | :py:class:`~xml.etree.ElementTree.Element`
        The element to parse. Must be a <map> tag.
    **kwargs
        Additional keyword arguments to pass to the constructor. Values from
        these arguments will override values parsed from the element.

    Returns
    -------
    Map
        A Map object representing the parsed element.

    Raises
    ------
    ValueError
        If the element is not a <map> tag.
    TypeError
        If the unicode attribute is missing from the element, or if any extra
        attribute is found in the element or passed as a keyword argument.
    """
    if str(element.tag) != "map":
      raise ValueError(f"Expected a <map> tag but got {element.tag!r}")
    return Map(**dict(element.attrib) | kwargs)

  @tp.overload
  def to_element(
    self,
    engine: tp.Literal[ENGINE.LXML] = ENGINE.LXML,
    add_extra: bool = False,
    **kwargs,
  ) -> lxet._Element: ...
  @tp.overload
  def to_element(
    self,
    engine: tp.Literal[ENGINE.PYTHON] = ENGINE.PYTHON,
    add_extra: bool = False,
    **kwargs,
  ) -> pyet.Element: ...
  def to_element(
    self,
    engine: tp.Literal[ENGINE.LXML, ENGINE.PYTHON] = ENGINE.LXML,
    add_extra: bool = False,
    **kwargs,
  ) -> lxet._Element | pyet.Element:
    """
    Converts a Map object to an xml <map/> element.

    Parameters
    ----------
    engine : ENGINE, optional
        The xml engine to use to create the Element, either python's standard
        library or lxml, by default "lxml"
    add_extra : bool, optional
        Whether to add extra attributes to the resulting Element, by default False.
    **kwargs
        Additional attributes to add to the resulting Element. If add_extra is
        False, any extra attribute passed as a keyword argument will be ignored.


    .. warning::
        If add_extra is True, any extra attribute passed as a keyword argument
        will be added to the resulting Element, even if it is not a valid
        attribute for a <map> tag or the value is not a string.

    Returns
    -------
    :external:py:class:`~lxml.etree._Element` | :py:class:`~xml.etree.ElementTree.Element`
        A xml Element representing the Map object.

    Raises
    ------
    TypeError
        If any attribute's type deosn't match its expected type.
    ValueError
        If the engine is not recognized.
    """
    return _make_elem(
      "map",
      _make_xml_attrs(self, add_extra=add_extra, **kwargs),
      engine,
    )


@dc.dataclass(
  kw_only=True,
  slots=True,
  unsafe_hash=True,
)
class Ude:
  """
  A dataclass representing a <ude> element in a tmx file.

  *User-Defined Encoding* - The <ude> element is used to specify a set of
  user-defined characters and/or, optionally their mapping from Unicode to
  the user-defined encoding.
  """

  name: str = dc.field(
    hash=True,
    compare=True,
  )
  """
  The name of the element. Its value is not defined by the standard. Required.
  """
  base: tp.Optional[str] = dc.field(
    hash=True,
    compare=True,
    default=None,
  )
  """
  *Base encoding* - The encoding upon which the re-mapping is based. One of the
  [IANA] recommended "charset identifier", if possible. Optional, by default None.
  """
  maps: abc.Sequence[Map] = dc.field(
    hash=True,
    compare=True,
    default_factory=list,
    metadata={"exclude": True},
  )
  """
  A Sequence of Map objects representing the mappings from Unicode to the
  user-defined encoding. Optional, by default an empty list.
  """

  @classmethod
  def from_element(cls, element: pyet.Element | lxet._Element, **kwargs) -> Ude:
    """
    Create a Ude object from an xml <ude> element.

    Parameters
    ----------
    element : :external:py:class:`~lxml.etree._Element` | :py:class:`~xml.etree.ElementTree.Element`
        The element to parse. Must be a <ude> tag.
    **kwargs
        Additional keyword arguments to pass to the Constructor. Values from
        these arguments will override values parsed from the element.


    .. note::
        if `maps` is supplied as a keyword argument, the function will use that
        value instead of parsing the element's children.

    Returns
    -------
    Ude
        A Ude object representing the parsed element.

    Raises
    ------
    ValueError
        If the element is not a <ude> tag.
    TypeError
        If the unicode attribute is missing from the element, or if any extra
        attribute is found in the element or passed as a keyword argument.
    """
    if str(element.tag) != "ude":
      raise ValueError(f"Expected a <ude> tag but got {element.tag!r}")
    maps = kwargs.pop("maps", None)
    if maps is None:
      if len(element):
        maps = [Map.from_element(map_) for map_ in element.iter("map")]
      else:
        maps = []
    return Ude(**dict(element.attrib) | kwargs, maps=maps)

  @tp.overload
  def to_element(
    self, engine: tp.Literal[ENGINE.LXML], add_extra: bool = False, **kwargs
  ) -> lxet._Element: ...
  @tp.overload
  def to_element(
    self, engine: tp.Literal[ENGINE.PYTHON], add_extra: bool = False, **kwargs
  ) -> pyet.Element: ...
  def to_element(
    self,
    engine: tp.Literal[ENGINE.LXML, ENGINE.PYTHON] = ENGINE.LXML,
    add_extra: bool = False,
    **kwargs,
  ) -> lxet._Element | pyet.Element:
    """
    Converts a Ude object to an xml <ude> element. All of the Element's Map
    objects are also converted to xml elements using the ENGINE passed as the
    engine argument and added as children of the resulting <ude> element.

    Parameters
    ----------
    engine : ENGINE, optional
        The xml engine to use to create the Element, either python's standard
        library or lxml, by default "lxml"
    add_extra : bool, optional
        Whether to add extra attributes to the resulting Element, by default False.
    **kwargs
        Additional attributes to add to the resulting Element. If add_extra is
        False, any extra attribute passed as a keyword argument will be ignored.


    .. warning::
        If add_extra is True, any extra attribute passed as a keyword argument
        will be added to the resulting Element, even if it is not a valid
        attribute for a <ude> tag or the value is not a string.

    Returns
    -------
    :external:py:class:`~lxml.etree._Element` | :py:class:`~xml.etree.ElementTree.Element`
        A xml Element representing the Ude object.

    Raises
    ------
    TypeError
        If any attribute's type deosn't match its expected type.
    ValueError
        If the engine is not recognized.
    """
    elem = _make_elem(
      "ude",
      _make_xml_attrs(self, add_extra=add_extra, **kwargs),
      engine,
    )

    if len(self.maps):
      for map_ in self.maps:
        if not self.base and map_.code:
          raise ValueError("base must be set if at least one map has a code attribute")
        elem.append(map_.to_element(engine))  # type: ignore
    return elem


@dc.dataclass(
  kw_only=True,
  slots=True,
  unsafe_hash=True,
)
class Note:
  """
  A dataclass representing a <note> element in a tmx file, generally used for
  comments.
  """

  text: str = dc.field(
    hash=True,
    compare=True,
    metadata={"exclude": True},
  )
  """
  The text of the Note. Required.
  """
  lang: tp.Optional[str] = dc.field(
    hash=True,
    compare=True,
    default=None,
    metadata={"export_name": "{http://www.w3.org/XML/1998/namespace}lang"},
  )
  """
  The language of the Note. A language code as described in the [RFC 3066].
  Not case-sensitive. Optional, by default None.
  """
  encoding: tp.Optional[str] = dc.field(
    hash=True,
    compare=True,
    default=None,
    metadata={"export_name": "o-encoding"},
  )
  """
  The original encoding of the text. One of the [IANA] recommended "charset
  identifier", if possible. Optional, by default None.
  """

  @classmethod
  def from_element(cls, element: pyet.Element | lxet._Element, **kwargs) -> Note:
    """
    Create a Note object from an xml <note> element.

    Parameters
    ----------
    element : :external:py:class:`~lxml.etree._Element` | :py:class:`~xml.etree.ElementTree.Element`
        The element to parse. Must be a <note> tag.
    **kwargs
        Additional keyword arguments to pass to the Constructor. Values from
        these arguments will override values parsed from the element.


    .. note::
        if `maps` is supplied as a keyword argument, the function will use that
        value instead of parsing the element's children.

    Returns
    -------
    Note
        A Note object representing the parsed element.

    Raises
    ------
    ValueError
        If the element is not a <note> tag.
    TypeError
        If the unicode attribute is missing from the element, or if any extra
        attribute is found in the element or passed as a keyword argument.
    """
    if str(element.tag) != "note":
      raise ValueError(f"Expected a <note> tag but got {element.tag!r}")
    lang = kwargs.get(
      "lang", element.attrib.get("{http://www.w3.org/XML/1998/namespace}lang")
    )
    encoding = kwargs.get("encoding", element.attrib.get("o-encoding"))
    text = kwargs.get("text", element.text)
    return Note(text=text, lang=lang, encoding=encoding)

  @tp.overload
  def to_element(
    self, engine: tp.Literal[ENGINE.LXML], add_extra: bool = False, **kwargs
  ) -> lxet._Element: ...
  @tp.overload
  def to_element(
    self, engine: tp.Literal[ENGINE.PYTHON], add_extra: bool = False, **kwargs
  ) -> pyet.Element: ...
  def to_element(
    self,
    engine: tp.Literal[ENGINE.LXML, ENGINE.PYTHON] = ENGINE.LXML,
    add_extra: bool = False,
    **kwargs,
  ) -> lxet._Element | pyet.Element:
    """
    Converts a Note object to an xml <note> element.

    Parameters
    ----------
    engine : ENGINE, optional
        The xml engine to use to create the Element, either python's standard
        library or lxml, by default "lxml"
    add_extra : bool, optional
        Whether to add extra attributes to the resulting Element, by default False.
    **kwargs
        Additional attributes to add to the resulting Element. If add_extra is
        False, any extra attribute passed as a keyword argument will be ignored.


    .. warning::
        If add_extra is True, any extra attribute passed as a keyword argument
        will be added to the resulting Element, even if it is not a valid
        attribute for a <note> tag or the value is not a string.

    Returns
    -------
    :external:py:class:`~lxml.etree._Element` | :py:class:`~xml.etree.ElementTree.Element`
        A xml Element representing the Note object.

    Raises
    ------
    TypeError
        If any attribute's type deosn't match its expected type.
    ValueError
        If the engine is not recognized.
    """
    elem = _make_elem(
      "note", _make_xml_attrs(self, add_extra=add_extra, **kwargs), engine
    )
    if not isinstance(self.text, str):
      raise TypeError(f"Expected str for text but got {type(self.text)!r}")
    elem.text = self.text
    return elem


@dc.dataclass(kw_only=True, slots=True, unsafe_hash=True)
class Prop:
  """
  A dataclass representing a <prop> element in a tmx file, used to define various
  properties of its parent element. These properties are not defined by the standard.
  The "text" can be any anything as long as it is in string format.

  By convention, values for the "type" attribute that are not defined by the standard
  should be prefixed with "x-". For example, "x-my-custom-type".
  """

  text: str = dc.field(
    hash=True,
    compare=True,
    metadata={"exclude": True},
  )
  """
  The text of the Prop. Required.
  """
  type: str = dc.field(
    hash=True,
    compare=True,
  )
  """
  The type of the Prop. Not defined by the standard. Required.
  """
  lang: tp.Optional[str] = dc.field(
    hash=True,
    compare=True,
    default=None,
    metadata={"export_name": "{http://www.w3.org/XML/1998/namespace}lang"},
  )
  """
  The language of the Prop. A language code as described in the [RFC 3066].
  Not case-sensitive. Optional, by default None.
  """
  encoding: tp.Optional[str] = dc.field(
    hash=True,
    compare=True,
    default=None,
    metadata={"export_name": "o-encoding"},
  )
  """
  The original encoding of the text. One of the [IANA] recommended "charset
  identifier", if possible. Optional, by default None.
  """

  @classmethod
  def from_element(cls, element: pyet.Element | lxet._Element, **kwargs) -> Prop:
    """
    Create a Prop object from an xml <prop> element.

    Parameters
    ----------
    element : :external:py:class:`~lxml.etree._Element` | :py:class:`~xml.etree.ElementTree.Element`
        The element to parse. Must be a <prop> tag.
    **kwargs
        Additional keyword arguments to pass to the Constructor. Values from
        these arguments will override values parsed from the element.


    .. prop::
        if `maps` is supplied as a keyword argument, the function will use that
        value instead of parsing the element's children.

    Returns
    -------
    Prop
        A Prop object representing the parsed element.

    Raises
    ------
    ValueError
        If the element is not a <prop> tag.
    TypeError
        If the unicode attribute is missing from the element, or if any extra
        attribute is found in the element or passed as a keyword argument.
    """
    if str(element.tag) != "prop":
      raise ValueError(f"Expected a <prop> tag but got {element.tag!r}")
    lang = kwargs.get(
      "lang", element.attrib.get("{http://www.w3.org/XML/1998/namespace}lang")
    )
    encoding = kwargs.get("encoding", element.attrib.get("o-encoding"))
    text = kwargs.get("text", element.text)
    type_ = kwargs.get("type", element.attrib.get("type"))
    return Prop(text=text, lang=lang, encoding=encoding, type=type_)

  @tp.overload
  def to_element(
    self, engine: tp.Literal[ENGINE.LXML], add_extra: bool = False, **kwargs
  ) -> lxet._Element: ...
  @tp.overload
  def to_element(
    self, engine: tp.Literal[ENGINE.PYTHON], add_extra: bool = False, **kwargs
  ) -> pyet.Element: ...
  def to_element(
    self,
    engine: tp.Literal[ENGINE.LXML, ENGINE.PYTHON] = ENGINE.LXML,
    add_extra: bool = False,
    **kwargs,
  ) -> lxet._Element | pyet.Element:
    """
    Converts a Prop object to an xml <prop> element.

    Parameters
    ----------
    engine : ENGINE, optional
        The xml engine to use to create the Element, either python's standard
        library or lxml, by default "lxml"
    add_extra : bool, optional
        Whether to add extra attributes to the resulting Element, by default False.
    **kwargs
        Additional attributes to add to the resulting Element. If add_extra is
        False, any extra attribute passed as a keyword argument will be ignored.


    .. warning::
        If add_extra is True, any extra attribute passed as a keyword argument
        will be added to the resulting Element, even if it is not a valid
        attribute for a <prop> tag or the value is not a string.

    Returns
    -------
    :external:py:class:`~lxml.etree._Element` | :py:class:`~xml.etree.ElementTree.Element`
        A xml Element representing the Prop object.

    Raises
    ------
    TypeError
        If any attribute's type deosn't match its expected type.
    ValueError
        If the engine is not recognized.
    """
    elem = _make_elem(
      "prop", _make_xml_attrs(self, add_extra=add_extra, **kwargs), engine
    )
    if not isinstance(self.text, str):
      raise TypeError(f"Expected str for text but got {type(self.text)!r}")
    elem.text = self.text
    return elem


@dc.dataclass(kw_only=True, slots=True, unsafe_hash=True)
class Header:
  creationtool: str = dc.field(
    hash=True,
    compare=True,
  )
  creationtoolversion: str = dc.field(
    hash=True,
    compare=True,
  )
  segtype: SEGTYPE = dc.field(
    hash=True,
    compare=True,
  )
  tmf: str = dc.field(
    hash=True,
    compare=True,
    metadata={"export_name": "o-tmf"},
  )
  adminlang: str = dc.field(
    hash=True,
    compare=True,
  )
  srclang: str = dc.field(
    hash=True,
    compare=True,
  )
  datatype: str = dc.field(
    hash=True,
    compare=True,
  )
  encoding: tp.Optional[str] = dc.field(
    default=None,
    hash=True,
    compare=True,
    metadata={"export_name": "o-encoding"},
  )
  creationdate: tp.Optional[dt.datetime] = dc.field(
    default=None,
    hash=True,
    compare=True,
  )
  creationid: tp.Optional[str] = dc.field(
    default=None,
    hash=True,
    compare=True,
  )
  changedate: tp.Optional[dt.datetime] = dc.field(
    default=None,
    hash=True,
    compare=True,
  )
  changeid: tp.Optional[str] = dc.field(
    default=None,
    hash=True,
    compare=True,
  )
  notes: abc.Sequence[Note] = dc.field(
    default_factory=list,
    hash=True,
    compare=True,
    metadata={"exclude": True},
  )
  props: abc.Sequence[Prop] = dc.field(
    default_factory=list,
    hash=True,
    compare=True,
    metadata={"exclude": True},
  )
  udes: abc.Sequence[Ude] = dc.field(
    default_factory=list,
    hash=True,
    compare=True,
    metadata={"exclude": True},
  )

  @classmethod
  def from_element(cls, element: pyet.Element | lxet._Element, **kwargs) -> Header:
    if str(element.tag) != cls.__name__.lower():
      raise ValueError(f"Expected a {cls.__name__.lower()} tag but got {element.tag!r}")
    creationtool = kwargs.get("creationtool", element.attrib.get("creationtool"))
    creationtoolversion = kwargs.get(
      "creationtoolversion", element.attrib.get("creationtoolversion")
    )
    segtype = kwargs.get("segtype", element.attrib.get("segtype"))
    tmf = kwargs.get("tmf", element.attrib.get("o-tmf"))
    adminlang = kwargs.get("adminlang", element.attrib.get("adminlang"))
    srclang = kwargs.get("srclang", element.attrib.get("srclang"))
    datatype = kwargs.get("datatype", element.attrib.get("datatype"))
    encoding = kwargs.get("encoding", element.attrib.get("o-encoding"))
    creationdate = kwargs.get("creationdate", element.attrib.get("creationdate"))
    creationid = kwargs.get("creationid", element.attrib.get("creationid"))
    changedate = kwargs.get("changedate", element.attrib.get("changedate"))
    changeid = kwargs.get("changeid", element.attrib.get("changeid"))
    if creationdate is not None:
      try:
        creationdate = dt.datetime.fromisoformat(creationdate)
      except (ValueError, TypeError):
        warn(f"could not parse {creationdate!r} as a datetime object.")
    if changedate is not None:
      try:
        changedate = dt.datetime.fromisoformat(changedate)
      except (ValueError, TypeError):
        warn(f"could not parse {changedate!r} as a datetime object.")
    if segtype is not None:
      try:
        segtype = SEGTYPE(segtype)
      except (ValueError, TypeError):
        warn(
          f"Expected one of 'block', 'paragraph', 'sentence' or 'phrase' for segtype but got {segtype!r}."
        )
    return Header(
      creationtool=creationtool,
      creationtoolversion=creationtoolversion,
      segtype=segtype,
      tmf=tmf,
      adminlang=adminlang,
      srclang=srclang,
      datatype=datatype,
      encoding=encoding,
      creationdate=creationdate,
      creationid=creationid,
      changedate=changedate,
      changeid=changeid,
      notes=notes
      if (notes := kwargs.get("notes")) is not None
      else _parse_notes(element),
      props=props
      if (props := kwargs.get("props")) is not None
      else _parse_props(element),
      udes=udes
      if (udes := kwargs.get("udes")) is not None
      else [Ude.from_element(ude) for ude in element.iter("ude")],
    )

  @tp.overload
  def to_element(
    self, engine: tp.Literal["lxml"], add_extra: bool = False, **kwargs
  ) -> lxet._Element: ...
  @tp.overload
  def to_element(
    self, engine: tp.Literal["python"], add_extra: bool = False, **kwargs
  ) -> pyet.Element: ...
  def to_element(
    self,
    engine: tp.Literal["lxml", "python"] = "lxml",
    add_extra: bool = False,
    **kwargs,
  ) -> lxet._Element | pyet.Element:
    elem = _make_elem(
      "header", _make_xml_attrs(self, add_extra=add_extra, **kwargs), engine
    )
    elem.extend(note.to_element(engine) for note in self.notes)
    elem.extend(prop.to_element(engine) for prop in self.props)  # type: ignore
    elem.extend(ude.to_element(engine) for ude in self.udes)  # type: ignore
    return elem


@dc.dataclass(kw_only=True, slots=True, unsafe_hash=True)
class Tuv:
  segment: abc.Sequence[str | Bpt | Ept | Ph | It | Hi | Ut] = dc.field(
    default_factory=list,
    hash=True,
    compare=True,
    metadata={"exclude": True},
  )
  lang: str = dc.field(
    hash=True,
    compare=True,
    metadata={"export_name": "{http://www.w3.org/XML/1998/namespace}lang"},
  )
  encoding: tp.Optional[str] = dc.field(
    hash=True,
    compare=True,
    default=None,
    metadata={"export_name": "o-encoding"},
  )
  datatype: tp.Optional[str] = dc.field(
    default=None,
    hash=True,
    compare=True,
  )
  usagecount: tp.Optional[int] = dc.field(
    default=None,
    hash=True,
    compare=True,
  )
  lastusagedate: tp.Optional[dt.datetime] = dc.field(
    default=None,
    hash=True,
    compare=True,
  )
  creationtool: tp.Optional[str] = dc.field(
    default=None,
    hash=True,
    compare=True,
  )
  creationtoolversion: tp.Optional[str] = dc.field(
    default=None,
    hash=True,
    compare=True,
  )
  creationdate: tp.Optional[dt.datetime] = dc.field(
    default=None,
    hash=True,
    compare=True,
  )
  creationid: tp.Optional[str] = dc.field(
    default=None,
    hash=True,
    compare=True,
  )
  changedate: tp.Optional[dt.datetime] = dc.field(
    default=None,
    hash=True,
    compare=True,
  )
  tmf: tp.Optional[str] = dc.field(
    default=None,
    hash=True,
    compare=True,
  )
  changeid: tp.Optional[str] = dc.field(
    default=None,
    hash=True,
    compare=True,
  )
  notes: abc.Sequence[Note] = dc.field(
    default_factory=list,
    hash=True,
    compare=True,
    metadata={"exclude": True},
  )
  props: abc.Sequence[Prop] = dc.field(
    default_factory=list,
    hash=True,
    compare=True,
    metadata={"exclude": True},
  )

  @classmethod
  def from_element(cls, element: pyet.Element | lxet._Element, **kwargs) -> Tuv:
    if str(element.tag) != cls.__name__.lower():
      raise ValueError(f"Expected a {cls.__name__.lower()} tag but got {element.tag!r}")
    lang = kwargs.get(
      "lang", element.attrib.get("{http://www.w3.org/XML/1998/namespace}lang")
    )
    encoding = kwargs.get("encoding", element.attrib.get("o-encoding"))
    datatype = kwargs.get("datatype", element.attrib.get("datatype"))
    usagecount = kwargs.get("usagecount", element.attrib.get("usagecount"))
    lastusagedate = kwargs.get("lastusagedate", element.attrib.get("lastusagedate"))
    creationtool = kwargs.get("creationtool", element.attrib.get("creationtool"))
    creationtoolversion = kwargs.get(
      "creationtoolversion", element.attrib.get("creationtoolversion")
    )
    creationdate = kwargs.get("creationdate", element.attrib.get("creationdate"))
    creationid = kwargs.get("creationid", element.attrib.get("creationid"))
    changedate = kwargs.get("changedate", element.attrib.get("changedate"))
    tmf = kwargs.get("tmf", element.attrib.get("o-tmf"))
    changeid = kwargs.get("changeid", element.attrib.get("changeid"))
    if kwargs.get("segment") is None:
      if (segment := element.find("seg")) is None:
        raise ValueError("could not find segment")
      segment_ = _parse_content(segment)
    if creationdate is not None:
      try:
        creationdate = dt.datetime.fromisoformat(creationdate)
      except (ValueError, TypeError):
        warn(f"could not parse {creationdate!r} as a datetime object.")
    if changedate is not None:
      try:
        changedate = dt.datetime.fromisoformat(changedate)
      except (ValueError, TypeError):
        warn(f"could not parse {changedate!r} as a datetime object.")
    if lastusagedate is not None:
      try:
        lastusagedate = dt.datetime.fromisoformat(lastusagedate)
      except (ValueError, TypeError):
        warn(f"could not parse {lastusagedate!r} as a datetime object.")
    if usagecount is not None:
      try:
        usagecount = int(usagecount)
      except (ValueError, TypeError):
        warn(f"could not parse {usagecount!r} as an int.")
    return Tuv(
      segment=segment_,  # type: ignore
      lang=lang,
      encoding=encoding,
      datatype=datatype,
      usagecount=usagecount,
      lastusagedate=lastusagedate,
      creationtool=creationtool,
      creationtoolversion=creationtoolversion,
      creationdate=creationdate,
      creationid=creationid,
      changedate=changedate,
      tmf=tmf,
      changeid=changeid,
      notes=notes
      if (notes := kwargs.get("notes")) is not None
      else _parse_notes(element),
      props=props
      if (props := kwargs.get("props")) is not None
      else _parse_props(element),
    )

  @tp.overload
  def to_element(
    self, engine: tp.Literal["lxml"], add_extra: bool = False, **kwargs
  ) -> lxet._Element: ...
  @tp.overload
  def to_element(
    self, engine: tp.Literal["python"], add_extra: bool = False, **kwargs
  ) -> pyet.Element: ...
  def to_element(
    self,
    engine: tp.Literal["lxml", "python"] = "lxml",
    add_extra: bool = False,
    **kwargs,
  ) -> lxet._Element | pyet.Element:
    elem = _make_elem(
      "tuv", _make_xml_attrs(self, add_extra=add_extra, **kwargs), engine
    )
    elem.extend(note.to_element(engine) for note in self.notes)  # type: ignore
    elem.extend(prop.to_element(engine) for prop in self.props)  # type: ignore
    seg = _make_elem("seg", dict(), engine)
    _add_content(seg, self.segment, engine, (str, Bpt, Ept, Ph, It, Hi, Ut))  # type: ignore
    elem.append(seg)  # type: ignore
    return elem


@dc.dataclass(kw_only=True, slots=True, unsafe_hash=True)
class Tu:
  tuid: tp.Optional[str] = dc.field(
    default=None,
    hash=True,
    compare=True,
  )
  encoding: tp.Optional[str] = dc.field(
    hash=True,
    compare=True,
    default=None,
    metadata={"export_name": "o-encoding"},
  )
  datatype: tp.Optional[str] = dc.field(
    default=None,
    hash=True,
    compare=True,
  )
  usagecount: tp.Optional[int] = dc.field(
    default=None,
    hash=True,
    compare=True,
  )
  lastusagedate: tp.Optional[dt.datetime] = dc.field(
    default=None,
    hash=True,
    compare=True,
  )
  creationtool: tp.Optional[str] = dc.field(
    default=None,
    hash=True,
    compare=True,
  )
  creationtoolversion: tp.Optional[str] = dc.field(
    default=None,
    hash=True,
    compare=True,
  )
  creationdate: tp.Optional[dt.datetime] = dc.field(
    default=None,
    hash=True,
    compare=True,
  )
  creationid: tp.Optional[str] = dc.field(
    default=None,
    hash=True,
    compare=True,
  )
  changedate: tp.Optional[dt.datetime] = dc.field(
    default=None,
    hash=True,
    compare=True,
  )
  segtype: tp.Optional[SEGTYPE] = dc.field(
    default=None,
    hash=True,
    compare=True,
  )
  changeid: tp.Optional[str] = dc.field(
    default=None,
    hash=True,
    compare=True,
  )
  tmf: tp.Optional[str] = dc.field(
    default=None,
    hash=True,
    compare=True,
  )
  srclang: tp.Optional[str] = dc.field(
    default=None,
    hash=True,
    compare=True,
  )
  tuvs: abc.Sequence[Tuv] = dc.field(
    default_factory=list,
    hash=True,
    compare=True,
    metadata={"exclude": True},
  )
  notes: abc.Sequence[Note] = dc.field(
    default_factory=list,
    hash=True,
    compare=True,
    metadata={"exclude": True},
  )
  props: abc.Sequence[Prop] = dc.field(
    default_factory=list,
    hash=True,
    compare=True,
    metadata={"exclude": True},
  )

  @classmethod
  def from_element(cls, element: pyet.Element | lxet._Element, **kwargs) -> Tu:
    if str(element.tag) != cls.__name__.lower():
      raise ValueError(f"Expected a {cls.__name__.lower()} tag but got {element.tag!r}")
    tuid = kwargs.get("tuid", element.attrib.get("tuid"))
    encoding = kwargs.get("encoding", element.attrib.get("o-encoding"))
    datatype = kwargs.get("datatype", element.attrib.get("datatype"))
    usagecount = kwargs.get("usagecount", element.attrib.get("usagecount"))
    lastusagedate = kwargs.get("lastusagedate", element.attrib.get("lastusagedate"))
    creationtool = kwargs.get("creationtool", element.attrib.get("creationtool"))
    creationtoolversion = kwargs.get(
      "creationtoolversion", element.attrib.get("creationtoolversion")
    )
    creationdate = kwargs.get("creationdate", element.attrib.get("creationdate"))
    creationid = kwargs.get("creationid", element.attrib.get("creationid"))
    changedate = kwargs.get("changedate", element.attrib.get("changedate"))
    segtype = kwargs.get("segtype", element.attrib.get("segtype"))
    tmf = kwargs.get("tmf", element.attrib.get("o-tmf"))
    changeid = kwargs.get("changeid", element.attrib.get("changeid"))
    srclang = kwargs.get("srclang", element.attrib.get("srclang"))
    if creationdate is not None:
      try:
        creationdate = dt.datetime.fromisoformat(creationdate)
      except (ValueError, TypeError):
        warn(f"could not parse {creationdate!r} as a datetime object.")
    if changedate is not None:
      try:
        changedate = dt.datetime.fromisoformat(changedate)
      except (ValueError, TypeError):
        warn(f"could not parse {changedate!r} as a datetime object.")
    if lastusagedate is not None:
      try:
        lastusagedate = dt.datetime.fromisoformat(lastusagedate)
      except (ValueError, TypeError):
        warn(f"could not parse {lastusagedate!r} as a datetime object.")
    if usagecount is not None:
      try:
        usagecount = int(usagecount)
      except (ValueError, TypeError):
        warn(f"could not parse {usagecount!r} as an int.")
    if segtype is not None:
      try:
        segtype = SEGTYPE(segtype)
      except (ValueError, TypeError):
        warn(
          f"Expected one of 'block', 'paragraph', 'sentence' or 'phrase' for segtype but got {segtype!r}."
        )
    return Tu(
      tuid=tuid,
      encoding=encoding,
      datatype=datatype,
      usagecount=usagecount,
      lastusagedate=lastusagedate,
      creationtool=creationtool,
      creationtoolversion=creationtoolversion,
      creationdate=creationdate,
      creationid=creationid,
      changedate=changedate,
      segtype=segtype,
      tmf=tmf,
      changeid=changeid,
      srclang=srclang,
      tuvs=tuvs if (tuvs := kwargs.get("tuvs")) is not None else _parse_tuvs(element),
      notes=notes
      if (notes := kwargs.get("notes")) is not None
      else _parse_notes(element),
      props=props
      if (props := kwargs.get("props")) is not None
      else _parse_props(element),
    )

  @tp.overload
  def to_element(
    self, engine: tp.Literal["lxml"], add_extra: bool = False, **kwargs
  ) -> lxet._Element: ...
  @tp.overload
  def to_element(
    self, engine: tp.Literal["python"], add_extra: bool = False, **kwargs
  ) -> pyet.Element: ...
  def to_element(
    self,
    engine: tp.Literal["lxml", "python"] = "lxml",
    add_extra: bool = False,
    **kwargs,
  ) -> lxet._Element | pyet.Element:
    elem = _make_elem(
      "tu", _make_xml_attrs(self, add_extra=add_extra, **kwargs), engine
    )
    elem.extend(note.to_element(engine) for note in self.notes)  # type: ignore
    elem.extend(prop.to_element(engine) for prop in self.props)  # type: ignore
    elem.extend(tuv.to_element(engine) for tuv in self.tuvs)  # type: ignore
    return elem


@dc.dataclass(kw_only=True, slots=True, unsafe_hash=True)
class Tmx:
  header: tp.Optional[Header] = dc.field(
    default=None,
    hash=True,
    compare=True,
    metadata={"exclude": True},
  )
  tus: abc.Sequence[Tu] = dc.field(
    default_factory=list,
    hash=True,
    compare=True,
    metadata={"exclude": True},
  )

  @classmethod
  def from_element(cls, element: pyet.Element | lxet._Element, **kwargs) -> Tmx:
    if str(element.tag) != cls.__name__.lower():
      raise ValueError(f"Expected a {cls.__name__.lower()} tag but got {element.tag!r}")
    header = kwargs.get("header", None)
    if header is None:
      if (header_elem := element.find("header")) is None:
        raise ValueError("could not find header")
      header = Header.from_element(header_elem)
    tus_ = kwargs.get("tus", None)
    if tus_ is None:
      if (body := element.find("body")) is None:
        raise ValueError("could not find body")
      tus_ = _parse_tus(body)
    return Tmx(header=header, tus=tus_)

  @tp.overload
  def to_element(
    self, engine: tp.Literal["lxml"], add_extra: bool = False, **kwargs
  ) -> lxet._Element: ...
  @tp.overload
  def to_element(
    self, engine: tp.Literal["python"], add_extra: bool = False, **kwargs
  ) -> pyet.Element: ...
  def to_element(
    self,
    engine: tp.Literal["lxml", "python"] = "lxml",
  ) -> lxet._Element | pyet.Element:
    elem = _make_elem("tmx", {"version": "1.4"}, engine)
    elem.append(self.header.to_element(engine))  # type: ignore
    body = _make_elem("body", dict(), engine)
    elem.append(body)  # type: ignore
    body.extend(tu.to_element(engine) for tu in self.tus)  # type: ignore
    return elem


@dc.dataclass(
  kw_only=True,
  slots=True,
  unsafe_hash=True,
)
class Bpt:
  content: abc.Sequence[str | Sub] = dc.field(
    default_factory=list,
    hash=True,
    compare=True,
    metadata={"exclude": True},
  )
  i: int = dc.field(
    hash=True,
    compare=True,
  )
  x: tp.Optional[int] = dc.field(
    hash=True,
    compare=True,
    default=None,
  )
  type: tp.Optional[str] = dc.field(
    hash=True,
    compare=True,
    default=None,
  )

  @classmethod
  def from_element(cls, element: pyet.Element | lxet._Element, **kwargs) -> Bpt:
    if str(element.tag) != cls.__name__.lower():
      raise ValueError(f"Expected a {cls.__name__.lower()} tag but got {element.tag!r}")
    i = kwargs.get("i", element.attrib.get("i"))
    x = kwargs.get("x", element.attrib.get("x"))
    type_ = kwargs.get("type", element.attrib.get("type"))
    try:
      i = int(i)
    except (ValueError, TypeError):
      warn(f"Expected int for i but got {type(i)!r}")
    if x is not None:
      try:
        x = int(x)
      except (ValueError, TypeError):
        warn(f"Expected int for x but got {type(x)!r}")
    content = kwargs.get("content", _parse_content(element))
    return Bpt(content=content, i=i, x=x, type=type_)

  @tp.overload
  def to_element(
    self, engine: tp.Literal["lxml"], add_extra: bool = False, **kwargs
  ) -> lxet._Element: ...
  @tp.overload
  def to_element(
    self, engine: tp.Literal["python"], add_extra: bool = False, **kwargs
  ) -> pyet.Element: ...
  def to_element(
    self,
    engine: tp.Literal["lxml", "python"] = "lxml",
    add_extra: bool = False,
    **kwargs,
  ) -> lxet._Element | pyet.Element:
    elem = _make_elem(
      "bpt", _make_xml_attrs(self, add_extra=add_extra, **kwargs), engine
    )
    _add_content(elem, kwargs.get("content", self.content), engine, (str, Sub))
    return elem


@dc.dataclass(
  kw_only=True,
  slots=True,
  unsafe_hash=True,
)
class Ept:
  content: abc.Sequence[str | Sub] = dc.field(
    default_factory=list,
    hash=True,
    compare=True,
    metadata={"exclude": True},
  )
  i: int = dc.field(
    hash=True,
    compare=True,
  )

  @classmethod
  def from_element(cls, element: pyet.Element | lxet._Element, **kwargs) -> Ept:
    if str(element.tag) != cls.__name__.lower():
      raise ValueError(f"Expected a {cls.__name__.lower()} tag but got {element.tag!r}")
    i = kwargs.get("i", element.attrib.get("i"))
    try:
      i = int(i)
    except (ValueError, TypeError):
      warn(f"Expected int for i but got {type(i)!r}")
    content = kwargs.get("content", _parse_content(element))
    return Ept(i=i, content=content)

  @tp.overload
  def to_element(
    self, engine: tp.Literal["lxml"], add_extra: bool = False, **kwargs
  ) -> lxet._Element: ...
  @tp.overload
  def to_element(
    self, engine: tp.Literal["python"], add_extra: bool = False, **kwargs
  ) -> pyet.Element: ...
  def to_element(
    self,
    engine: tp.Literal["lxml", "python"] = "lxml",
    add_extra: bool = False,
    **kwargs,
  ) -> lxet._Element | pyet.Element:
    elem = _make_elem(
      "ept", _make_xml_attrs(self, add_extra=add_extra, **kwargs), engine
    )
    _add_content(elem, kwargs.get("content", self.content), engine, (str, Sub))
    return elem


@dc.dataclass(
  kw_only=True,
  slots=True,
  unsafe_hash=True,
)
class Sub:
  content: abc.Sequence[str | Bpt | Ept | It | Ph | Hi | Ut] = dc.field(
    default_factory=list,
    hash=True,
    compare=True,
    metadata={"exclude": True},
  )
  datatype: tp.Optional[str] = dc.field(
    hash=True,
    compare=True,
    default=None,
  )
  type: tp.Optional[str] = dc.field(
    hash=True,
    compare=True,
    default=None,
  )

  @classmethod
  def from_element(cls, element: pyet.Element | lxet._Element, **kwargs) -> Sub:
    if str(element.tag) != cls.__name__.lower():
      raise ValueError(f"Expected a {cls.__name__.lower()} tag but got {element.tag!r}")
    content = kwargs.get("content", _parse_content(element))
    datatype = kwargs.get("datatype", element.attrib.get("datatype"))
    type_ = kwargs.get("type", element.attrib.get("type"))
    return Sub(content=content, datatype=datatype, type=type_)

  @tp.overload
  def to_element(
    self, engine: tp.Literal["lxml"], add_extra: bool = False, **kwargs
  ) -> lxet._Element: ...
  @tp.overload
  def to_element(
    self, engine: tp.Literal["python"], add_extra: bool = False, **kwargs
  ) -> pyet.Element: ...
  def to_element(
    self,
    engine: tp.Literal["lxml", "python"] = "lxml",
    add_extra: bool = False,
    **kwargs,
  ) -> lxet._Element | pyet.Element:
    elem = _make_elem(
      "sub", _make_xml_attrs(self, add_extra=add_extra, **kwargs), engine
    )
    _add_content(
      elem, kwargs.get("content", self.content), engine, (str, Bpt, Ept, It, Ph, Hi, Ut)
    )
    return elem


@dc.dataclass(
  kw_only=True,
  slots=True,
  unsafe_hash=True,
)
class It:
  content: abc.Sequence[str | Sub] = dc.field(
    default_factory=list,
    hash=True,
    compare=True,
    metadata={"exclude": True},
  )
  pos: POS = dc.field(
    hash=True,
    compare=True,
  )
  x: tp.Optional[int] = dc.field(
    hash=True,
    compare=True,
    default=None,
  )
  type: tp.Optional[str] = dc.field(
    hash=True,
    compare=True,
    default=None,
  )

  @classmethod
  def from_element(cls, element: pyet.Element | lxet._Element, **kwargs) -> It:
    if str(element.tag) != cls.__name__.lower():
      raise ValueError(f"Expected a {cls.__name__.lower()} tag but got {element.tag!r}")
    pos = kwargs.get("pos", element.attrib.get("pos"))
    x = kwargs.get("x", element.attrib.get("x"))
    type_ = kwargs.get("type", element.attrib.get("type"))
    try:
      x = int(x)
    except (ValueError, TypeError):
      warn(f"Expected int for x but got {x!r}")
    try:
      pos = POS(pos)
    except (ValueError, TypeError):
      warn(f"Expected one of 'begin' or 'end' for pos but got {pos!r}")
    content = kwargs.get("content", _parse_content(element))
    return It(pos=pos, x=x, type=type_, content=content)

  @tp.overload
  def to_element(
    self, engine: tp.Literal["lxml"], add_extra: bool = False, **kwargs
  ) -> lxet._Element: ...
  @tp.overload
  def to_element(
    self, engine: tp.Literal["python"], add_extra: bool = False, **kwargs
  ) -> pyet.Element: ...
  def to_element(
    self,
    engine: tp.Literal["lxml", "python"] = "lxml",
    add_extra: bool = False,
    **kwargs,
  ) -> lxet._Element | pyet.Element:
    elem = _make_elem(
      "it", _make_xml_attrs(self, add_extra=add_extra, **kwargs), engine
    )
    _add_content(elem, kwargs.get("content", self.content), engine, (str, Sub))
    return elem


@dc.dataclass(
  kw_only=True,
  slots=True,
  unsafe_hash=True,
)
class Ph:
  content: abc.Sequence[str | Sub] = dc.field(
    default_factory=list,
    hash=True,
    compare=True,
    metadata={"exclude": True},
  )
  x: tp.Optional[int] = dc.field(
    hash=True,
    default=None,
    compare=True,
  )
  assoc: tp.Optional[ASSOC] = dc.field(
    hash=True,
    default=None,
    compare=True,
  )
  type: tp.Optional[str] = dc.field(
    hash=True,
    compare=True,
    default=None,
  )

  @classmethod
  def from_element(cls, element: pyet.Element | lxet._Element, **kwargs) -> Ph:
    if str(element.tag) != cls.__name__.lower():
      raise ValueError(f"Expected a {cls.__name__.lower()} tag but got {element.tag!r}")
    x = kwargs.get("x", element.attrib.get("x"))
    assoc = kwargs.get("assoc", element.attrib.get("pos"))
    type_ = kwargs.get("type", element.attrib.get("type"))
    try:
      x = int(x)
    except (ValueError, TypeError):
      warn(f"Expected int for x but got {x!r}")
    try:
      assoc = ASSOC(assoc)
    except (ValueError, TypeError):
      warn(f"Expected one of 'p', 'f' or 'b' for pos but got {assoc!r}")
    content = kwargs.get("content", _parse_content(element))
    return Ph(assoc=assoc, x=x, type=type_, content=content)

  @tp.overload
  def to_element(
    self, engine: tp.Literal["lxml"], add_extra: bool = False, **kwargs
  ) -> lxet._Element: ...
  @tp.overload
  def to_element(
    self, engine: tp.Literal["python"], add_extra: bool = False, **kwargs
  ) -> pyet.Element: ...
  def to_element(
    self,
    engine: tp.Literal["lxml", "python"] = "lxml",
    add_extra: bool = False,
    **kwargs,
  ) -> lxet._Element | pyet.Element:
    elem = _make_elem(
      "ph", _make_xml_attrs(self, add_extra=add_extra, **kwargs), engine
    )
    _add_content(elem, kwargs.get("content", self.content), engine, (str, Sub))
    return elem


@dc.dataclass(
  kw_only=True,
  slots=True,
  unsafe_hash=True,
)
class Hi:
  content: abc.Sequence[str | Sub] = dc.field(
    default_factory=list,
    hash=True,
    compare=True,
    metadata={"exclude": True},
  )
  x: tp.Optional[int] = dc.field(
    hash=True,
    default=None,
    compare=True,
  )
  type: tp.Optional[str] = dc.field(
    hash=True,
    compare=True,
    default=None,
  )

  @classmethod
  def from_element(cls, element: pyet.Element | lxet._Element, **kwargs) -> Hi:
    if str(element.tag) != cls.__name__.lower():
      raise ValueError(f"Expected a {cls.__name__.lower()} tag but got {element.tag!r}")
    x = kwargs.get("x", element.attrib.get("x"))
    type_ = kwargs.get("type", element.attrib.get("type"))
    try:
      x = int(x)
    except (ValueError, TypeError):
      warn(f"Expected int for x but got {x!r}")
    content = kwargs.get("content", _parse_content(element))
    return Hi(x=x, type=type_, content=content)

  @tp.overload
  def to_element(
    self, engine: tp.Literal["lxml"], add_extra: bool = False, **kwargs
  ) -> lxet._Element: ...
  @tp.overload
  def to_element(
    self, engine: tp.Literal["python"], add_extra: bool = False, **kwargs
  ) -> pyet.Element: ...
  def to_element(
    self,
    engine: tp.Literal["lxml", "python"] = "lxml",
    add_extra: bool = False,
    **kwargs,
  ) -> lxet._Element | pyet.Element:
    elem = _make_elem(
      "hi", _make_xml_attrs(self, add_extra=add_extra, **kwargs), engine
    )
    _add_content(elem, kwargs.get("content", self.content), engine, (str, Sub))
    return elem


@dc.dataclass(
  kw_only=True,
  slots=True,
  unsafe_hash=True,
)
@deprecated("Deprecated since TMX 1.4")
class Ut:
  content: abc.Sequence[str | Sub] = dc.field(
    default_factory=list,
    hash=True,
    compare=True,
    metadata={"exclude": True},
  )
  x: tp.Optional[int] = dc.field(
    hash=True,
    default=None,
    compare=True,
  )

  @classmethod
  def from_element(cls, element: pyet.Element | lxet._Element, **kwargs) -> Ut:
    if str(element.tag) != cls.__name__.lower():
      raise ValueError(f"Expected a {cls.__name__.lower()} tag but got {element.tag!r}")
    x = kwargs.get("x", element.attrib.get("x"))
    try:
      x = int(x)
    except (ValueError, TypeError):
      warn(f"Expected int for x but got {x!r}")
    content = kwargs.get("content", _parse_content(element))
    return Ut(x=x, content=content)

  @tp.overload
  def to_element(
    self, engine: tp.Literal["lxml"], add_extra: bool = False, **kwargs
  ) -> lxet._Element: ...
  @tp.overload
  def to_element(
    self, engine: tp.Literal["python"], add_extra: bool = False, **kwargs
  ) -> pyet.Element: ...
  def to_element(
    self,
    engine: tp.Literal["lxml", "python"] = "lxml",
    add_extra: bool = False,
    **kwargs,
  ) -> lxet._Element | pyet.Element:
    elem = _make_elem(
      "ut", _make_xml_attrs(self, add_extra=add_extra, **kwargs), engine
    )
    _add_content(elem, kwargs.get("content", self.content), engine, (str, Sub))
    return elem


TmxElement = tp.Union[
  Tmx,
  Header,
  Ude,
  Map,
  Note,
  Prop,
  Tu,
  Tuv,
  Bpt,
  Ept,
  Hi,
  It,
  Ph,
  Sub,
  Ut,
]

StructuralElement = tp.Union[
  Header,
  Note,
  Prop,
  Ude,
  Map,
  Tu,
  Tuv,
  Tmx,
]

InlineElement = tp.Union[
  Bpt,
  Ept,
  Hi,
  It,
  Ph,
  Sub,
  Ut,
]
