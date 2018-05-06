#!/usr/bin/env python3
# Copyright 2018, Joren Van Onder
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import argparse
import sys
from subprocess import run


class Packer:
    def __init__(self):
        self.buffer = 0  # buffer can safely be backed by an int because ints are unbounded
        self.bit_length = 0

    def pack(self, content, length):
        CONTENT_MASK = 2 ** length - 1
        assert content & CONTENT_MASK == content, '{} does not fit in {} bits'.format(content, length)

        self.buffer <<= length
        self.buffer |= content
        self.bit_length += length

    def flush(self):
        # byte-align buffer
        pad_bits = 8 - (self.bit_length % 8 or 8)
        self.buffer <<= pad_bits
        self.bit_length += pad_bits

        filled_bytes = self.bit_length // 8

        BYTEMASK = 2 ** 8 - 1
        packed_bytes = bytes()
        while filled_bytes > 0:
            shifts = (filled_bytes - 1) * 8
            packed_bytes += bytes([(self.buffer >> shifts) & BYTEMASK])
            filled_bytes -= 1

        self.buffer = 0
        self.bit_length = 0

        return packed_bytes


class Unpacker:
    def __init__(self, data):
        self.data = data
        self.data_bit_string = ''.join([format(b, '08b') for b in data])
        self.bit_index = 0

    def is_empty(self):
        return self.bit_index >= len(self.data_bit_string)

    def unpack(self, length):
        assert not self.is_empty(), 'trying to unpack but no data left'

        bit_string = self.data_bit_string[self.bit_index:self.bit_index + length]
        self.bit_index += length
        return bit_string


class Node:
    def __init__(self, occurences, content=None):
        self.content = content
        self.occurences = occurences
        self.left = self.right = None

    def __str__(self):
        return '{} (n={})'.format(self.content, self.occurences)

    def _content_for_label(self):
        REPLACEMENTS = [('\\', '\\\\'), ('"', '\\"')]
        label = chr(self.content) if self.content else ''

        for pattern, replacement in REPLACEMENTS:
            label = label.replace(pattern, replacement)

        return label

    def to_dot(self):
        label = ''
        if self.left:
            label += '{} -> {} [label="0"];'.format(repr(self), repr(self.left))
        if self.right:
            label += '{} -> {} [label="1"];'.format(repr(self), repr(self.right))
        label += '{} [label="{}"];'.format(repr(self), '(n={})\n{}'.format(self.occurences, self._content_for_label()))
        return label

    def to_dict(self, path=None):
        if not path:
            path = ''

        if self.content is not None:
            return {self.content: path}
        else:
            left_dict = self.left.to_dict(path + '0') if self.left else {}
            right_dict = self.right.to_dict(path + '1') if self.right else {}
            left_dict.update(right_dict)
            return left_dict

    def to_dot_string(self):
        out = ''
        out = self.to_dot()

        if self.left:
            out += '\n' + self.left.to_dot_string()
        if self.right:
            out += '\n' + self.right.to_dot_string()

        return out


class HuffmanTree:
    def __init__(self, data):
        self.data = data
        symbols = set(data)
        nodes = []

        for symbol in symbols:
            occurences = data.count(symbol)
            nodes.append(Node(occurences, symbol))

        while len(nodes) > 1:
            node1 = min(nodes, key=lambda n: n.occurences)
            nodes.remove(node1)
            node2 = min(nodes, key=lambda n: n.occurences)
            nodes.remove(node2)

            parent = Node(node1.occurences + node2.occurences)
            parent.left = node1
            parent.right = node2
            nodes.append(parent)

        self.root = nodes[0]

    def to_dict(self):
        return self.root.to_dict()

    def to_dot_string(self):
        return self.root.to_dot_string()

    def render_graph(self, filename):
        graph_content_string = 'digraph G {' + self.to_dot_string() + '}'
        run(['dot', '-Tsvg', '-o', filename], input=graph_content_string, encoding='ascii')

    def compress(self):
        # 1) amount of items in dict (8 bits, don't support empty dict)
        # 2) for each item encode:
        #    - symbol (8 bits)
        #    - length (8 bits)
        #    - value (variable bits)
        # 3) because output might be padded at the end, encode amount of symbols (32 bits)
        # 4) for each symbol in data:
        #    - code (variable bits)
        packer = Packer()
        coding_dict = self.to_dict()

        # fit this in 8 bits, don't support empty coding_dict
        packer.pack(len(coding_dict) - 1, 8)

        for symbol, code in coding_dict.items():
            packer.pack(symbol, 8)
            packer.pack(len(code), 8)
            code_value = int(code, 2)
            packer.pack(code_value, len(code))

        packer.pack(len(self.data), 32)
        for symbol in self.data:
            code = coding_dict[symbol]
            packer.pack(int(code, 2), len(code))

        return packer.flush()


def decompress(data):
    unpacker = Unpacker(data)
    codes_to_read = int(unpacker.unpack(8), 2) + 1
    coding_dict = {}

    while codes_to_read:
        symbol = int(unpacker.unpack(8), 2)
        code_length = int(unpacker.unpack(8), 2)
        code = unpacker.unpack(code_length)
        coding_dict[code] = bytes([symbol])
        codes_to_read -= 1

    symbols_to_read = int(unpacker.unpack(32), 2)
    decompressed = b''
    bit_string = ''
    while symbols_to_read:
        bit_string += unpacker.unpack(1)

        if bit_string in coding_dict:
            decompressed += coding_dict[bit_string]
            bit_string = ''
            symbols_to_read -= 1

    return decompressed


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--graph', help='Generate a visual representation of the encoding.')
    parser.add_argument('action', choices=['compress', 'decompress'])
    args = parser.parse_args()
    if args.action == 'compress':
        tree = HuffmanTree(sys.stdin.buffer.read())
        if args.graph:
            tree.render_graph(args.graph)
        sys.stdout.buffer.write(tree.compress())
    else:
        decompressed = decompress(sys.stdin.buffer.read())
        sys.stdout.buffer.write(decompressed)
