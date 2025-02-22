# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
# pylint: disable=missing-module-docstring,missing-function-docstring,missing-class-docstring

import math
import sys
from typing import List

import pytest
import tvm
import tvm.testing
from tvm._ffi import register_func
from tvm.error import TVMError
from tvm.meta_schedule import TuneContext
from tvm.meta_schedule.schedule_rule import PyScheduleRule
from tvm.meta_schedule.space_generator import PostOrderApply
from tvm.meta_schedule.utils import derived_object
from tvm.script import tir as T
from tvm.target import Target
from tvm.tir.schedule import BlockRV, Schedule

# pylint: disable=invalid-name,no-member,line-too-long,too-many-nested-blocks,no-self-argument,
# fmt: off

@tvm.script.ir_module
class Matmul:
    @T.prim_func
    def main(a: T.handle, b: T.handle, c: T.handle) -> None:
        T.func_attr({"global_symbol": "main"})
        A = T.match_buffer(a, (1024, 1024), "float32")
        B = T.match_buffer(b, (1024, 1024), "float32")
        C = T.match_buffer(c, (1024, 1024), "float32")
        for i, j, k in T.grid(1024, 1024, 1024):
            with T.block("matmul"):
                vi, vj, vk = T.axis.remap("SSR", [i, j, k])
                with T.init():
                    C[vi, vj] = 0.0
                C[vi, vj] = C[vi, vj] + A[vi, vk] * B[vk, vj]


@tvm.script.ir_module
class DuplicateMatmul:
    @T.prim_func
    def main(a: T.handle, b: T.handle, c: T.handle) -> None:
        T.func_attr({"global_symbol": "main"})
        A = T.match_buffer(a, (1024, 1024), "float32")
        B = T.match_buffer(b, (1024, 1024), "float32")
        C = T.match_buffer(c, (1024, 1024), "float32")
        for i, j, k in T.grid(1024, 1024, 1024):
            with T.block("matmul"):
                vi, vj, vk = T.axis.remap("SSR", [i, j, k])
                with T.init():
                    C[vi, vj] = 0.0
                C[vi, vj] = C[vi, vj] + A[vi, vk] * B[vk, vj]
        for i, j, k in T.grid(1024, 1024, 1024):
            with T.block("matmul"):
                vi, vj, vk = T.axis.remap("SSR", [i, j, k])
                C[vi, vj] = C[vi, vj] + A[vi, vk] * B[vk, vj]


@tvm.script.ir_module
class TrinityMatmul:
    @T.prim_func
    def main(a: T.handle, d: T.handle) -> None:
        T.func_attr({"global_symbol": "main"})
        A = T.match_buffer(a, (1024, 1024), "float32")
        B = T.alloc_buffer((1024, 1024), "float32")
        C = T.alloc_buffer((1024, 1024), "float32")
        D = T.match_buffer(d, (1024, 1024), "float32")
        for i, j in T.grid(1024, 1024):
            with T.block("A"):
                vi, vj = T.axis.remap("SS", [i, j])
                B[vi, vj] = A[vi, vj] * 2.0
        for i, j in T.grid(1024, 1024):
            with T.block("B"):
                vi, vj = T.axis.remap("SS", [i, j])
                C[vi, vj] = B[vi, vj] + 3.0
        for i, j in T.grid(1024, 1024):
            with T.block("C"):
                vi, vj = T.axis.remap("SS", [i, j])
                D[vi, vj] = C[vi, vj] * 5.0


@tvm.script.ir_module
class TrinityMatmulProcessedForReference:
    @T.prim_func
    def main(a: T.handle, d: T.handle) -> None:
        # function attr dict
        T.func_attr({"global_symbol": "main"})
        A = T.match_buffer(a, [1024, 1024], dtype="float32")
        D = T.match_buffer(d, [1024, 1024], dtype="float32")
        # body
        # with tir.block("root")
        B = T.alloc_buffer([1024, 1024], dtype="float32")
        for i0_0, i1_0, i0_1, i1_1 in T.grid(16, 64, 64, 16):
            with T.block("A"):
                vi = T.axis.S(1024, i0_0 * 64 + i0_1)
                vj = T.axis.S(1024, i1_0 * 16 + i1_1)
                T.reads([A[vi, vj]])
                T.writes([B[vi, vj]])
                B[vi, vj] = A[vi, vj] * T.float32(2)
        for i0_0, i1_0, i0_1, i1_1 in T.grid(16, 64, 64, 16):
            with T.block("C"):
                vi = T.axis.S(1024, i0_0 * 64 + i0_1)
                vj = T.axis.S(1024, i1_0 * 16 + i1_1)
                T.reads([B[vi, vj]])
                T.writes([D[vi, vj]])
                D[vi, vj] = (B[vi, vj] + T.float32(3)) * T.float32(5)


@tvm.script.ir_module
class MatmulCustomized:
    @T.prim_func
    def main(a: T.handle, b: T.handle, c: T.handle) -> None:
        T.func_attr({"global_symbol": "main"})
        A = T.match_buffer(a, (1024, 1024), "float32")
        B = T.match_buffer(b, (1024, 1024), "float32")
        C = T.match_buffer(c, (1024, 1024), "float32")
        with T.block("root"):
            for i, j, k in T.grid(1024, 1024, 1024):
                with T.block("matmul"):
                    T.block_attr({"schedule_rule": "tvm.meta_schedule.test.custom_search_space"})
                    vi, vj, vk = T.axis.remap("SSR", [i, j, k])
                    with T.init():
                        C[vi, vj] = 0.0
                    C[vi, vj] = C[vi, vj] + A[vi, vk] * B[vk, vj]

# fmt: on
# pylint: enable=invalid-name,no-member,line-too-long,too-many-nested-blocks,no-self-argument


def _is_root(sch: Schedule, block: BlockRV) -> bool:
    return sch.get_sref(block).parent is None


def _check_correct(schedule: Schedule):
    trace = schedule.trace
    for inst in trace.decisions:
        assert math.prod(trace.decisions[inst]) == 1024


@derived_object
class WowSoFancyScheduleRule(PyScheduleRule):
    def initialize_with_tune_context(self, context: "TuneContext") -> None:
        pass

    def apply(self, sch: Schedule, block: BlockRV) -> List[Schedule]:
        if _is_root(sch, block):
            return [sch]
        new_sch = sch.copy()
        i, j, k = new_sch.get_loops(block=block)
        i_0, i_1, i_2, i_3 = new_sch.split(loop=i, factors=[2, 4, 64, 2])
        j_0, j_1, j_2, j_3 = new_sch.split(loop=j, factors=[4, 64, 2, 2])
        k_0, k_1 = new_sch.split(loop=k, factors=[32, 32])
        new_sch.reorder(i_0, j_0, i_1, j_1, k_0, i_2, j_2, k_1, i_3, j_3)
        return [new_sch]


@derived_object
class DoubleScheduleRule(PyScheduleRule):
    def initialize_with_tune_context(self, context: "TuneContext") -> None:
        pass

    def apply(self, sch: Schedule, block: BlockRV) -> List[Schedule]:
        if _is_root(sch, block):
            return [sch]
        new_sch = sch.copy()
        i, j, k = new_sch.get_loops(block=block)
        i_0, i_1, i_2, i_3 = new_sch.split(loop=i, factors=[4, 64, 2, 2])
        j_0, j_1, j_2, j_3 = new_sch.split(loop=j, factors=[2, 4, 64, 2])
        k_0, k_1 = new_sch.split(loop=k, factors=[32, 32])
        new_sch.reorder(i_0, j_0, i_1, j_1, k_0, i_2, j_2, k_1, i_3, j_3)
        result = [new_sch]
        new_sch = sch.copy()
        i, j, k = new_sch.get_loops(block=block)
        i_0, i_1, i_2, i_3 = new_sch.split(loop=i, factors=[4, 64, 2, 2])
        j_0, j_1, j_2, j_3 = new_sch.split(loop=j, factors=[2, 4, 64, 2])
        k_0, k_1 = new_sch.split(loop=k, factors=[32, 32])
        new_sch.reorder(i_0, j_0, i_1, j_1, k_0, i_2, j_2, k_1, i_3, j_3)
        result.append(new_sch)
        return result


@derived_object
class ReorderScheduleRule(PyScheduleRule):
    def initialize_with_tune_context(self, context: "TuneContext") -> None:
        pass

    def apply(self, sch: Schedule, block: BlockRV) -> List[Schedule]:
        if _is_root(sch, block):
            return [sch]
        new_sch = sch.copy()
        i_0, j_0, i_1, j_1, k_0, i_2, j_2, k_1, i_3, j_3 = new_sch.get_loops(block=block)
        new_sch.reorder(i_1, j_1, k_0, i_2, j_2, k_1, i_3, j_3, i_0, j_0)
        result = [new_sch]
        new_sch = sch.copy()
        i_0, j_0, i_1, j_1, k_0, i_2, j_2, k_1, i_3, j_3 = new_sch.get_loops(block=block)
        new_sch.reorder(i_1, j_3, i_0, j_0, j_1, k_0, i_2, j_2, k_1, i_3)
        result.append(new_sch)
        return result


def test_meta_schedule_post_order_apply():
    mod = Matmul
    context = TuneContext(
        mod=mod,
        target=Target("llvm"),
        task_name="Test Task",
        sch_rules=[WowSoFancyScheduleRule()],
    )
    post_order_apply = PostOrderApply()
    post_order_apply.initialize_with_tune_context(context)
    schs = post_order_apply.generate_design_space(mod)
    assert len(schs) == 1
    assert not tvm.ir.structural_equal(schs[0].mod, mod)
    _check_correct(schs[0])


def test_meta_schedule_post_order_apply_double():
    mod = Matmul
    context = TuneContext(
        mod=mod,
        target=Target("llvm"),
        task_name="Double Rules Task",
        sch_rules=[DoubleScheduleRule()],
    )
    post_order_apply = PostOrderApply()
    post_order_apply.initialize_with_tune_context(context)
    schs = post_order_apply.generate_design_space(mod)
    assert len(schs) == 2
    for sch in schs:
        assert not tvm.ir.structural_equal(sch.mod, mod)
        _check_correct(sch)


def test_meta_schedule_post_order_apply_multiple():
    mod = Matmul
    context = TuneContext(
        mod=mod,
        target=Target("llvm"),
        task_name="Double Rules Task",
        sch_rules=[DoubleScheduleRule(), ReorderScheduleRule()],
    )
    post_order_apply = PostOrderApply()
    post_order_apply.initialize_with_tune_context(context)
    schs = post_order_apply.generate_design_space(mod)
    assert len(schs) == 4
    for sch in schs:
        assert not tvm.ir.structural_equal(sch.mod, mod)
        _check_correct(sch)


def test_meta_schedule_post_order_apply_duplicate_matmul():
    mod = DuplicateMatmul
    context = TuneContext(
        mod=mod,
        target=Target("llvm"),
        task_name="Duplicate Matmul Task",
        sch_rules=[WowSoFancyScheduleRule()],
    )
    post_order_apply = PostOrderApply()
    post_order_apply.initialize_with_tune_context(context)
    with pytest.raises(
        TVMError,
        match=r".*TVMError: Check failed: \(block_names_.count\(block->name_hint\) == 0\)"
        r" is false: Duplicated block name matmul in function main not supported!",
    ):
        post_order_apply.generate_design_space(mod)


def test_meta_schedule_post_order_apply_remove_block():
    @derived_object
    class TrinityDouble(PyScheduleRule):
        def initialize_with_tune_context(self, context: "TuneContext") -> None:
            pass

        def apply(self, sch: Schedule, block: BlockRV) -> List[Schedule]:
            if _is_root(sch, block):
                return [sch]
            new_sch = sch.copy()
            i, j = new_sch.get_loops(block=block)
            i_0, i_1 = new_sch.split(loop=i, factors=[16, 64])
            j_0, j_1 = new_sch.split(loop=j, factors=[64, 16])
            new_sch.reorder(i_0, j_0, i_1, j_1)
            result = [new_sch]
            new_sch = sch.copy()
            i, j = new_sch.get_loops(block=block)
            i_0, i_1 = new_sch.split(loop=i, factors=[2, 512])
            j_0, j_1 = new_sch.split(loop=j, factors=[2, 512])
            new_sch.reorder(i_0, j_0, i_1, j_1)
            result.append(new_sch)
            return result

    @derived_object
    class RemoveBlock(PyScheduleRule):
        def initialize_with_tune_context(self, context: "TuneContext") -> None:
            pass

        def apply(self, sch: Schedule, block: BlockRV) -> List[Schedule]:
            if _is_root(sch, block):
                return [sch]
            sch = sch.copy()
            if sch.get(block).name_hint == "B":
                sch.compute_inline(block)
            return [sch]

    def correct_trace(a, b, c, d):
        return "\n".join(
            [
                'b0 = sch.get_block(name="A", func_name="main")',
                'b1 = sch.get_block(name="B", func_name="main")',
                'b2 = sch.get_block(name="C", func_name="main")',
                "sch.compute_inline(block=b1)",
                "l3, l4 = sch.get_loops(block=b2)",
                "l5, l6 = sch.split(loop=l3, factors=" + str(a) + ")",
                "l7, l8 = sch.split(loop=l4, factors=" + str(b) + ")",
                "sch.reorder(l5, l7, l6, l8)",
                "l9, l10 = sch.get_loops(block=b0)",
                "l11, l12 = sch.split(loop=l9, factors=" + str(c) + ")",
                "l13, l14 = sch.split(loop=l10, factors=" + str(d) + ")",
                "sch.reorder(l11, l13, l12, l14)",
            ]
        )

    mod = TrinityMatmul
    context = TuneContext(
        mod=mod,
        target=Target("llvm"),
        task_name="Remove Block Task",
        sch_rules=[RemoveBlock(), TrinityDouble()],
    )
    post_order_apply = PostOrderApply()
    post_order_apply.initialize_with_tune_context(context)
    schs = post_order_apply.generate_design_space(mod)
    assert len(schs) == 4
    for sch in schs:
        with pytest.raises(
            tvm.tir.schedule.schedule.ScheduleError,
            match="ScheduleError: An error occurred in the schedule primitive 'get-block'.",
        ):
            sch.get_block("B", "main")
        sch_trace = sch.trace.simplified(True)
        assert (
            str(sch_trace) == correct_trace([16, 64], [64, 16], [2, 512], [2, 512])
            or str(sch_trace) == correct_trace([2, 512], [2, 512], [2, 512], [2, 512])
            or str(sch_trace) == correct_trace([16, 64], [64, 16], [16, 64], [64, 16])
            or str(sch_trace) == correct_trace([2, 512], [2, 512], [16, 64], [64, 16])
        )


def test_meta_schedule_custom_search_space():
    mod = MatmulCustomized
    context = TuneContext(
        mod=mod,
        target=Target("llvm"),
        task_name="Custom Search Space Task",
        sch_rules=[],
    )
    post_order_apply = PostOrderApply()
    post_order_apply.initialize_with_tune_context(context)

    post_order_apply.generate_design_space(mod)

    called = False

    def custom_search_space_func(sch: Schedule, _: BlockRV) -> List[Schedule]:
        nonlocal called
        called = True
        return [sch]

    register_func("tvm.meta_schedule.test.custom_search_space", custom_search_space_func)

    post_order_apply.generate_design_space(mod)
    assert called


if __name__ == "__main__":
    tvm.testing.main()
