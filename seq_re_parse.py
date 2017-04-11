# coding:utf-8

__author__ = "GE Ning <https://github.com/gening/seq_regex>"
__copyright__ = "Copyright (C) 2017 GE Ning"
__license__ = "Apache License 2.0"
__version__ = "0.1.4"


class Flags(object):
    EX = 'EX'  # general expression
    EXP = 'EXP'  # automatic expansion
    EXT_START = 'EXT_S'  # non-capturing group pattern start
    EXT_END = 'EXT_E'  # non-capturing group pattern end
    GROUP_START = 'GRP_S'  # capturing group pattern start
    GROUP_END = 'GRP_E'  # capturing group pattern end
    GROUP_NAME = 'GRP_NAM'  # group name define
    TUPLE_START = 'TUP_S'  # tuple pattern start
    TUPLE_END = 'TUP_E'  # tuple pattern end
    SET_START = 'SET_S'  # tuple pattern start
    SET_END = 'SET_E'  # tuple pattern end
    SET_NEG = 'SET_NEG'  # negative sign
    LITERAL = 'LITERAL'  # need to be encoded


class SeqRegexParser(object):
    # the class wraps the parse function,
    # and manages the states of the global variables.

    def __init__(self):
        self._ndim = 0
        self._pattern_str = None
        self._placeholder_dict = None
        self._pattern_tokenized = None
        self._pattern_stack = None
        self.named_group_format_indices = None

    def _set(self, ndim, pattern_str, placeholder_dict):
        if isinstance(ndim, int) and ndim > 0:
            self._ndim = ndim
        else:
            raise ValueError('invalid number of dimensions')
        if pattern_str is not None:
            self._pattern_str = pattern_str
        else:
            raise ValueError('invalid pattern string')
        self._placeholder_dict = placeholder_dict
        self._pattern_tokenized = Tokenizer(pattern_str)
        self._pattern_stack = []
        self.named_group_format_indices = dict()

    @property
    def ndim(self):
        return self._ndim

    @property
    def pattern_str(self):
        return self._pattern_str

    @classmethod
    def _parse_indices(cls, indices_string):
        # parse the format string: `0,2:4`
        # return index_range_list = [(group_index_begin, group_index_end), ...]
        index_range_list = indices_string.split(u',')
        for ix, indices in enumerate(index_range_list):
            index_list = indices.split(u':')
            if len(index_list) == 1:
                index = int(index_list[0].strip())
                index_range_list[ix] = (index, index + 1)
            elif len(index_list) == 2:
                index_range_list[ix] = (int(index_list[0].strip()), int(index_list[1].strip()))
            else:
                raise ValueError
        return index_range_list

    def _parse_group_identifier(self, identifier_string):
        # parse the group identifier:
        # `name` => name, [(0, ndim)]
        # `name@` =>name, [(0, ndim)]
        # `name@format_string` => name, [(group_index_begin, group_index_end), ...]
        # `name@@` => name, None
        # return ('group_name', [(group_index_begin, group_index_end), ...])
        source = self._pattern_tokenized
        name = u''
        format_indices = []
        items = identifier_string.split(u'@')
        if len(items) > 0:
            name = items[0]
            if name == u'':
                raise source.error(u'missing group name', len(identifier_string) + 1)
        # A
        if len(items) == 1:
            format_indices.append((0, self._ndim))
        # A@ => ['A', '']
        # A@B => ['A', 'B']
        elif len(items) == 2:
            format_string = items[1]
            if format_string == u'':
                format_indices.append((0, self._ndim))
            elif format_string != u'':
                try:
                    format_indices = self._parse_indices(format_string)
                except ValueError:
                    raise source.error(u'invalid format indices `%s`' % format_string,
                                       len(format_string) + 1)
        # A@@ => ['A', '', '']
        elif len(items) == 3 and items[1] == u'' and items[2] == u'':
            format_indices = None
        # A@B@C => ['A', 'B', 'C']
        else:
            format_string = u'@'.join(items[1:])
            raise source.error(u'invalid format indices `%s`' % format_string,
                               len(format_string) + 1)
        return name, format_indices

    def _parse_placeholder(self, placeholder_name):
        # parse placeholder name in the pattern string
        # and substitute it by a set of placeholder values
        # through looking up placeholder_dict
        str_list = []
        # placeholder name
        placeholder_set = self._placeholder_dict.get(placeholder_name, placeholder_name)
        if hasattr(placeholder_set, '__iter__'):
            # list, set
            str_list.extend(placeholder_set)
        else:
            # a single string
            str_list.append(placeholder_set)
        return str_list

    def _parse_element(self, negative_flag, element_set):
        # parse the element as the following:
        #  None  <==>   `|`
        #  `A`   <==>  `A|`  <==>  `|A`
        # `^A`   <==> `^A|`  <==> `^|A`
        #  `A|B` !<=> `^A|B`
        # `\^`    ==>  ok
        #  `^`   <==>  `^|`     ==> error
        # given that A and B are the values of the same one element.
        # params: element_set = [([char1, char2, ...], pos), ...]
        # return: parsed = [(Flag, parsed_pattern), ...]
        source = self._pattern_tokenized
        parsed = self._pattern_stack

        if negative_flag >= 0:
            negatived = True
        else:
            negatived = False

        # avoid `placeholder|placeholder` => [["p11""p12"]["p2"]]
        # in which escaped `[` and `]` are misunderstand.
        # replaced by ["p11""p12""p2"]
        elements = []
        for value_chars, source_pos in element_set:
            value_str = u''.join(value_chars)  # value_chars = [a1, a2, ...]
            if value_str in self._placeholder_dict:
                for v in self._parse_placeholder(value_str):
                    elements.append([v, None])
            else:
                elements.append([value_str, source_pos])

        if len(elements) == 0:
            # nothing to be negatived
            if negatived:
                raise source.error(u'unexpected negative sign `^`', source.pos - negative_flag)
            # `.`
            else:
                parsed.append([Flags.EXP, u'.', source.pos - 1])
        elif not negatived and len(elements) == 1:
            # `A`
            value_str, source_pos = elements[0]
            parsed.append([Flags.LITERAL, value_str, source_pos])
        else:
            # `[AB]` `[^A]` `[^AB]`
            parsed.append([Flags.SET_START, u'[', None])
            if negatived:
                parsed.append([Flags.SET_NEG, u'^', negative_flag])
            for value_str, source_pos in elements:
                parsed.append([Flags.LITERAL, value_str, source_pos])
            parsed.append([Flags.SET_END, u']', None])

        # clear element_set
        element_set[:] = []
        return

    def _parse_tuple(self):
        # parse the tuple pattern as the following,
        # which is delimited by `/.../` excluding the delimited `/` and `/`:
        # `/X:/` `/X:Y/` `/:Y/`
        # `//` `/|/` `/:/` `/|:/``/:|/`
        # given that X and Y are elements.
        # in that all `(` and `)` in the elements are parsed as plain text,
        # which have no syntax meaning, the nested recursion of this function is not required.
        #
        # when `/`
        # => parse element
        # => add . if dim_index < ndim
        # when `:`
        # => parse element
        # => dim_index ++
        # when `|`
        # => add an element value to set
        # when `^`
        # => negative all elements if it's the first
        source = self._pattern_tokenized
        parsed = self._pattern_stack
        dim_index = 0
        element_list = []  # [(value_list, pos), ...] = [([char1, char2, ...], pos), ...]
        negative_flag = -1
        # open the `/`
        start_pos = source.pos - 1
        parsed.append([Flags.TUPLE_START, u'(?:', start_pos])
        while True:
            this = source.next
            this_pos = source.pos
            if this is None:
                # unexpected end of tuple pattern
                raise source.error(u'unbalanced slash `/`', source.pos - start_pos)
            if this == u'/':
                if negative_flag >= 0 or len(element_list) > 0:
                    self._parse_element(negative_flag, element_list)
                    # negative_flag = -1
                    dim_index += 1
                # check the consistency of dimensions
                # /a:bc:def/
                # ^ ^  ^   ^
                # 0 1  2   3
                dim_vacancy = self._ndim - dim_index
                if dim_vacancy > 0:
                    parsed.append([Flags.EXP, u'.' * dim_vacancy, None])
                break  # end of tuple pattern
            source.get()

            if this == u':':
                self._parse_element(negative_flag, element_list)
                negative_flag = -1
                # move dim_index forwards
                dim_index += 1
                if dim_index >= self._ndim:
                    raise source.error(u'out of dimension range')
            elif this == u'|':
                if source.next not in u'|:/':
                    # nothing to be alternated previously
                    # if len(element_list) == 0:
                    #    ignore raising source.error(u'unexpected alternate sign `|`')
                    # new value of the element
                    element_list.append(([], this_pos + 1))
            elif this == u'^' and len(element_list) == 0 and negative_flag < 0:
                # `^` has no special meaning if it’s not the first character in the set.
                # negatived = True
                negative_flag = this_pos
            else:
                if len(element_list) == 0:
                    element_list.append(([], this_pos))
                if this[0] == u'\\':
                    if this[1] in u'/:|\\':
                        element_list[-1][0].append(this[1])
                    elif this[1] == u'^' and len(element_list[0][0]) == 0:
                        # so only if it's the first character, `^` can be escaped.
                        element_list[-1][0].append(this[1])
                    else:
                        element_list[-1][0].append(this[0:2])
                else:
                    element_list[-1][0].append(this)
        # close the `/`
        parsed.append([Flags.TUPLE_END, u')', source.pos])
        return

    def _parse_group(self):
        # parse the group pattern inside the parentheses,
        #   which is delimited by `(...)` including the delimited `(` and `)`:
        # => separate the group extension prefix:
        #   `(?:...)`
        #   `(?P<name>...)`
        #   `(?P=name)`
        #   `(?#comment)`
        #   `(?(id/name)...)`
        #   `(?=...)`
        #   `(?!...)`
        #   `(?<=...)`
        #   `(?<!...)`
        # => if there is a sub pattern, then parse sub pattern
        # => separate the format indices of a named group from its name: `<name@0,2:4>`
        # => only `(pattern)` and `(?P<name>pattern)` will be counted as capturing groups,
        #    and assigned the group index.
        source = self._pattern_tokenized
        parsed = self._pattern_stack
        group = False  # capturing group flag
        # open group
        start_pos = source.pos - 1
        parsed.append([Flags.EXT_START, u'(', start_pos])
        # group content
        if source.match(u'?'):
            # this is an extension notation
            char = source.get()
            if char is None:
                raise source.error(u'unexpected end of pattern')
            elif char == u':':
                group = False
                # non-capturing group
                parsed.append([Flags.EX, u'?:', source.pos - 2])
            elif char == u'P':
                if source.match(u'<'):
                    group = True
                    parsed[-1][0] = Flags.GROUP_START
                    parsed.append([Flags.EX, u'?P<', source.pos - 3])
                    # named group: skip forward to end of name and format
                    identifier = source.get_until(u'>')  # terminator will be consumed silently
                    name, format_indices = self._parse_group_identifier(identifier)
                    self.named_group_format_indices[name] = format_indices
                    parsed.append([Flags.GROUP_NAME, name, source.pos - len(identifier) - 1])
                    parsed.append([Flags.EX, u'>', source.pos - 1])
                elif source.match(u'='):
                    parsed.append([Flags.EX, u'?P=', source.pos - 3])
                    # named back reference
                    name = source.get_until(u')', skip=False)  # terminator will be not consumed
                    parsed.append([Flags.EX, name, source.pos - len(name)])
                    # close the group
                    parsed.append([Flags.EXT_END, u')', source.pos])
                    # not contain any pattern
                    return
            elif char == u'#':
                # group = False
                parsed.pop(-1)  # pop the start of group
                # comment group ignores everything including `/.../`
                # source.get_until(u')', skip=False)  # terminator will be not consumed
                while True:
                    if source.next is None:
                        raise source.error("missing `)`, unterminated comment",
                                           source.pos - start_pos)
                    if source.match(u')', skip=False):
                        break
                    else:
                        source.get()
                # not contain any pattern
                return
            elif char in u'=!<':
                group = False
                # lookahead assertions
                if char == u'<':
                    char = source.get()
                    if char is None:
                        raise source.error(u'unexpected end of pattern')
                    if char not in u'=!':
                        raise source.error(u'unknown extension `?<%s`' % char, len(char) + 2)
                    else:
                        char = u'<' + char
                char = u'?' + char
                parsed.append([Flags.EX, char, source.pos - len(char)])
            elif char == u'(':
                group = False
                parsed.append([Flags.EX, u'?(', source.pos - 2])
                # conditional back reference group
                cond_name = source.get_until(u')')  # terminator will be consumed silently
                parsed.append([Flags.EX, cond_name, source.pos - len(cond_name) - 1])
                parsed.append([Flags.EX, u')', source.pos - 1])
            else:
                raise source.error(u'unknown extension `?%s`' % char, len(char) + 1)
                # parsed.append([Flags.EX, u'?' + char, source.pos - 2])
                # pass
        else:
            # without extension notation as an unnamed group
            group = True
            parsed[-1][0] = Flags.GROUP_START
            pass
        # group contains a sub pattern
        self._parse_sub()
        # close group
        if group:
            start_flag = Flags.GROUP_START
            end_flag = Flags.GROUP_END
        else:
            start_flag = Flags.EXT_START
            end_flag = Flags.EXT_END
        if parsed[-1][0] == start_flag:
            parsed.pop(-1)
        else:
            parsed.append([end_flag, u')', source.pos])
        return

    def _parse_sub(self):
        # parse the sub pattern `...`,
        # which maybe contain the group pattern `(...)` or the tuple pattern `/.../`:
        # => check invalid char outside of comments: [ ] \
        # => remove redundant char: whitespace
        # => count continuous dots separately,
        #    not replace regex pattern '.\+' => '(?:' + '.' * ndim + ')'
        # => deal with delimiter: `(group pattern)`, `/tuple pattern/`
        source = self._pattern_tokenized
        parsed = self._pattern_stack
        while True:
            # hold the position at source to retain the boundary
            this = source.next
            this_pos = source.pos
            if this is None:
                break  # end of pattern
            if this == u')':
                break  # end of group pattern
            # move index of the source forward
            source.get()

            if this[0] == u'\\':
                raise source.error(u'invalid escape expression `\\`', len(this))
            elif this in u'[]':
                raise source.error(u'invalid set indicator `%s`' % this, 1)
            elif this.isspace():
                pass
            elif this == u'.':
                parsed.append([Flags.EXP, u'(?:' + u'.' * self._ndim + u')', this_pos])
            elif this == u'(':
                # parse the whole group content `...` without consuming `(` and `)`
                self._parse_group()
                if not source.match(u')'):
                    # unexpected end of group pattern
                    raise source.error(u'unbalanced parenthesis `(`', source.pos - this_pos)
            elif this == u'/':
                # parse the tuple whole content `...` without consuming `(` and `)`
                self._parse_tuple()
                if not source.match(u'/'):
                    # unexpected end of group pattern
                    raise source.error(u'unbalanced slash `/`', source.pos - this_pos)
            elif this in u'*+?{,}0123456789' or this in u'^$' or this in u'|':
                # repeat
                # at beginning or end
                # branch
                parsed.append([Flags.EX, this, this_pos])
            else:
                raise source.error(u'unsupported syntax char `%s`' % this, 1)
        return

    def _parse_seq(self):
        # parse the whole pattern `...`
        # for the pattern `...)...`, parser will be stopped at `)` and an error will be raised.
        source = self._pattern_tokenized
        parsed = self._pattern_stack
        # parse the seq pattern
        self._parse_sub()
        # parsing exit before end of pattern
        if source.next is not None:
            # unexpected end of pattern
            assert source.next == u')'
            raise source.error(u'unbalanced parenthesis `)`')
        return parsed

    def parse(self, ndim, pattern_str, **placeholder_dict):
        # the main entry of functions.
        # parse the pattern by translating its syntax into the equivalent in regular expression
        # and return a pattern stack for future encode.
        self._set(ndim, pattern_str, placeholder_dict)
        parsed = self._parse_seq()
        return parsed

    def dump(self):
        # transform self._pattern_stack into pseudo regular expression string
        # for debugging or testing
        dump_stack = []
        if self._pattern_stack:
            for flag, string, pos in self._pattern_stack:
                if flag == Flags.LITERAL:
                    dump_stack.append(u'"%s"' % string)
                elif string is not None:
                    dump_stack.append(string)
        return u''.join(dump_stack)

    def get_pattern_str_by_name(self, group_name):
        # get original pattern string determined by group name
        start = end = step = -1
        for flag, string, pos in self._pattern_stack:
            if flag == Flags.GROUP_START:
                if step < 0:
                    start = pos
                else:
                    step += 1
            elif flag == Flags.GROUP_NAME:
                if step < 0 and string == group_name:
                    step = 0
            elif flag == Flags.GROUP_END:
                if step == 0:
                    end = pos
                    break
                elif step > 0:
                    step -= 1
        if start > -1 and end > -1:
            # `(?:P<name@@>pattern_str)`
            return self._pattern_str[start: end + 1]
        else:
            raise ValueError('unknown group name')

    def get_pattern_str_by_id(self, group_index):
        # get original pattern string determined by group index
        start = end = step = -1
        group_id = 0
        named = False
        if group_index == 0:
            return self._pattern_str
        for flag, string, pos in self._pattern_stack:
            if flag == Flags.GROUP_START:
                group_id += 1
                if group_id == group_index:
                    step = 0
                    start = pos
                else:
                    step += 1
            elif flag == Flags.GROUP_NAME and group_id == group_index:
                named = True
            elif flag == Flags.GROUP_END:
                if step == 0:
                    end = pos
                    break
                elif step > 0:
                    step -= 1
        if start > -1 and end > -1:
            if named:
                # `(?P<....>pattern_str)`
                return self._pattern_str[start: end + 1]
            else:
                # `(pattern_str)`
                return self._pattern_str[start: end + 1]
        else:
            raise ValueError('group index out of range')


class Tokenizer(object):
    # this class is based on the following but modified:
    # https://github.com/python/cpython/blob/master/Lib/sre_parse.py
    # https://svn.python.org/projects/python/trunk/Lib/sre_parse.py
    # python’s SRE structure can be learned from:
    # https://blog.labix.org/2003/06/16/understanding-pythons-sre-structure

    def __init__(self, string):
        self.string = string
        self.index = 0
        self.next = None
        self.__next()

    def __next(self):
        if self.index >= len(self.string):
            self.next = None
            return
        char = self.string[self.index]
        if char[0] == "\\":
            try:
                c = self.string[self.index + 1]
            except IndexError:
                raise self.error(u'bad escape in end')
            char += c
        self.index += len(char)
        self.next = char

    def match(self, char, skip=True):
        if char == self.next:
            if skip:
                self.__next()
            return True
        return False

    def get(self):
        this = self.next
        self.__next()
        return this

    def get_while(self, n, charset):
        result = u''
        for _ in range(n):
            c = self.next
            if c not in charset:
                break
            result += c
            self.__next()
        return result

    def get_until(self, terminator, skip=True):
        result = ''
        while True:
            c = self.next
            self.__next()
            if c is None:
                if not result:
                    raise self.error(u'missing characters')
                raise self.error(u'missing `%s`, unterminated characters' % terminator,
                                 len(result))
            if c == terminator:
                if not result:
                    raise self.error(u'missing character', 1)
                if not skip:
                    self.seek(self.index - 2)
                break
            result += c
        return result

    @property
    def pos(self):
        return self.tell()

    def tell(self):
        return self.index - len(self.next or u'')

    def seek(self, index):
        self.index = index
        self.__next()

    def error(self, msg, offset=0):
        position = self.tell() - offset
        # highlight the position of error
        return ValueError(u'%s at position %d\n%s\n%s' %
                          (msg, position, self.string, u'.' * position + u'^'))