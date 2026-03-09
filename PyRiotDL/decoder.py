from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from PyRiotDL.helper import BinaryReader, decompress_zstd, raw_handler
from PyRiotDL.models import Bundle, Chunk, Directory, GameFile, Language, Manifest

class ManifestDecoder:
    def __init__(self, raw: str | bytes | BinaryReader):
        self.reader = raw_handler(raw)
        if self.reader is None:
            raise ValueError("Unsupported input type decoder cant handle that, Must be str, bytes, or BinaryReader.")
        magic = self.reader.bytes_at(0, 4)
        if magic != b'RMAN':
            raise ValueError(f"Not a valid RMAN manifest. Got magic: {magic!r}")

        self._major: Optional[int] = None
        self._minor: Optional[int] = None
        self._content_offset: Optional[int] = None
        self._content_length: Optional[int] = None
        self._manifest_id: Optional[str] = None
        self._manifest: Optional[Manifest] = None

    @property
    def major(self) -> int:
        if self._major is None:
            self._major = self.reader.u8(4) # type: ignore
        return self._major

    @property
    def minor(self) -> int:
        if self._minor is None:
            self._minor = self.reader.u8(5) # type: ignore
        return self._minor

    @property
    def version(self) -> str:
        return f"{self.major}.{self.minor}"

    @property
    def content_offset(self) -> int:
        if self._content_offset is None:
            self._content_offset = self.reader.u32(8) # type: ignore
        return self._content_offset

    @property
    def content_length(self) -> int:
        if self._content_length is None:
            self._content_length = self.reader.u32(12) # type: ignore
        return self._content_length

    @property
    def manifest_id(self) -> str:
        if self._manifest_id is None:
            self._manifest_id = self.reader.bytes_at(20, 8).hex().upper() # type: ignore
        return self._manifest_id

    @property
    def manifest(self) -> Manifest:
        if self._manifest is None:
            self._manifest = self.__parse_flatbuffer()
        return self._manifest

    def __decompress_body(self) -> bytes:
        try:
            compressed = self.reader.data[self.content_offset:self.content_offset + self.content_length] # type: ignore
            if not compressed:
                raise ValueError("Manifest body is empty (zero content length or bad offset)")
            return decompress_zstd(compressed)
        except (IndexError, ValueError) as exc:
            raise ValueError(f"Failed to decompress manifest body: {exc}") from exc

    def __parser(self, fb: FlatBufferReader, index: int, parser_method) -> list:
        result = []
        try:
            vec = fb.field_vector_pos(fb.root(), index)
            if vec is not None:
                for i in range(fb.vector_len(vec)):
                    result.append(parser_method(fb, fb.vector_table_element(vec, i)))
        except Exception as exc:
            raise ValueError(f"FlatBuffer parse error at table index {index}: {exc}") from exc
        return result

    def __parse_flatbuffer(self) -> Manifest:
        try:
            fb = FlatBufferReader(self.__decompress_body())
            return Manifest(
                manifest_id = self.manifest_id,
                version = self.version,
                bundles = self.__parser(fb, 0, self.__parse_bundle),
                languages = self.__parser(fb, 1, self.__parse_language),
                files = self.__parser(fb, 2, self.__parse_file),
                directories = self.__parser(fb, 3, self.__parse_directory),
            )
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"Failed to parse manifest FlatBuffer: {exc}") from exc

    def __parse_bundle(self, fb: FlatBufferReader, bundle_table: int) -> Bundle:
        try:
            bundle_id = fb.field_u64(bundle_table, 0)
            chunks_vec = fb.field_vector_pos(bundle_table, 1)
            chunks = []
            co  = 0
            uco = 0
            if chunks_vec is not None:
                for i in range(fb.vector_len(chunks_vec)):
                    t = fb.vector_table_element(chunks_vec, i)
                    cid = fb.field_u64(t, 0)
                    cs = fb.field_u32(t, 1)
                    ucs = fb.field_u32(t, 2)
                    _chunk = Chunk(
                        chunk_id = cid,
                        compressed_offset = co,
                        compressed_size = cs,
                        uncompressed_offset = uco,
                        uncompressed_size = ucs,
                    )
                    chunks.append(_chunk)
                    co  += cs
                    uco += ucs
            return Bundle(bundle_id=bundle_id, chunks=chunks)
        except Exception as exc:
            raise ValueError(f"Failed to parse bundle at table {bundle_table}: {exc}") from exc

    def __parse_language(self, fb: FlatBufferReader, lang_table: int) -> Language:
        try:
            return Language(
                lang_id = fb.field_u8(lang_table, 0),
                name = fb.field_string(lang_table, 1) or "",
            )
        except Exception as exc:
            raise ValueError(f"Failed to parse language at table {lang_table}: {exc}") from exc

    def __parse_directory(self, fb: FlatBufferReader, dir_table: int) -> Directory:
        try:
            return Directory(
                dir_id = fb.field_u64(dir_table, 0),
                parent_id = fb.field_u64(dir_table, 1),
                name = fb.field_string(dir_table, 2) or "",
            )
        except Exception as exc:
            raise ValueError(f"Failed to parse directory at table {dir_table}: {exc}") from exc

    def __parse_file(self, fb: FlatBufferReader, file_table: int) -> GameFile:
        try:
            chunk_ids_vec = fb.field_vector_pos(file_table, 7)
            chunk_ids = []
            if chunk_ids_vec is not None:
                for i in range(fb.vector_len(chunk_ids_vec)):
                    chunk_ids.append(fb.vector_u64_element(chunk_ids_vec, i))
            return GameFile(
                file_id = fb.field_u64(file_table, 0),
                directory_id = fb.field_u64(file_table, 1),
                size = fb.field_u32(file_table, 2),
                name = fb.field_string(file_table, 3) or "",
                locale_flags = fb.field_u64(file_table, 4),
                chunk_ids = chunk_ids,
            )
        except Exception as exc:
            raise ValueError(f"Failed to parse file at table {file_table}: {exc}") from exc


class FlatBufferReader:
    """
    Minimal FlatBuffer reader for RMAN. No external flatbuffers library needed.

    Every Table has a vtable storing field offsets.
    All pointers are relative — value 20 at pos 100 means jump to 120.
    """

    def __init__(self, data: bytes):
        self.r = BinaryReader(data)

    def root(self) -> int:
        return self.r.i32(0)

    def follow(self, pos: int) -> int:
        return pos + self.r.i32(pos)

    def vtable_of(self, table_pos: int) -> int:
        return table_pos - self.r.i32(table_pos)

    def field_pos(self, table_pos: int, field_index: int) -> Optional[int]:
        vtable      = self.vtable_of(table_pos)
        vtable_size = self.r.u16(vtable)
        entry_pos   = vtable + 4 + field_index * 2
        if entry_pos + 2 > vtable + vtable_size:
            return None
        offset = self.r.u16(entry_pos)
        return (table_pos + offset) if offset else None

    def field_u8 (self, t: int, i: int, d: int = 0) -> int:
        p = self.field_pos(t, i); return self.r.u8(p)  if p is not None else d

    def field_u16(self, t: int, i: int, d: int = 0) -> int:
        p = self.field_pos(t, i); return self.r.u16(p) if p is not None else d

    def field_u32(self, t: int, i: int, d: int = 0) -> int:
        p = self.field_pos(t, i); return self.r.u32(p) if p is not None else d

    def field_u64(self, t: int, i: int, d: int = 0) -> int:
        p = self.field_pos(t, i); return self.r.u64(p) if p is not None else d

    def field_string(self, table_pos: int, field_index: int) -> Optional[str]:
        pos = self.field_pos(table_pos, field_index)
        if pos is None:
            return None
        str_pos = self.follow(pos)
        length  = self.r.u32(str_pos)
        return self.r.bytes_at(str_pos + 4, length).decode("utf-8", errors="replace")

    def field_vector_pos(self, table_pos: int, field_index: int) -> Optional[int]:
        pos = self.field_pos(table_pos, field_index)
        return self.follow(pos) if pos is not None else None

    def vector_len(self, vec_pos: int) -> int:
        return self.r.u32(vec_pos)

    def vector_element(self, vec_pos: int, index: int, element_size: int = 4) -> int:
        return vec_pos + 4 + index * element_size

    def vector_table_element(self, vec_pos: int, index: int) -> int:
        return self.follow(self.vector_element(vec_pos, index, 4))

    def vector_u64_element(self, vec_pos: int, index: int) -> int:
        return self.r.u64(self.vector_element(vec_pos, index, 8))

    def vector_u32_element(self, vec_pos: int, index: int) -> int:
        return self.r.u32(self.vector_element(vec_pos, index, 4))