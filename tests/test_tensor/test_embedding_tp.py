import torch
from colossalai.tensor import ColoTensor, ShardSpec
from torch.nn import functional as F
from functools import partial

import colossalai
import pytest
import torch
import torch.multiprocessing as mp
from colossalai.testing import rerun_if_address_is_in_use
from colossalai.utils import free_port
from colossalai.tensor import ColoTensorSpec, ComputePattern, ComputeSpec, DistSpecManager, ProcessGroup
from _utils import tensor_equal, tensor_shard_equal


def init_1d_row(weight, pg: ProcessGroup):
    spec = (ShardSpec([0], [pg.tp_world_size()]), ComputeSpec(ComputePattern.TP1D))
    with DistSpecManager.no_grad():
        weight.set_tensor_spec(*spec)


def init_1d_col(weight, pg: ProcessGroup):
    spec = (ShardSpec([-1], [pg.tp_world_size()]), ComputeSpec(ComputePattern.TP1D))
    with DistSpecManager.no_grad():
        weight.set_tensor_spec(*spec)


def run_with_spec(spec_init_func, pg: ProcessGroup):
    model = torch.nn.Embedding(12, 32).cuda()
    weight = ColoTensor(torch.nn.Parameter(model.weight.detach()), ColoTensorSpec(pg))
    spec_init_func(weight, pg)
    x = torch.tensor((0, 3, 6, 9)).cuda()
    out = model(x)
    colo_out = F.embedding(x, weight)
    assert tensor_equal(out, colo_out)
    grad = torch.rand_like(out)
    out.backward(grad)
    colo_out.backward(grad)
    # compare grad inside a TP group
    assert tensor_shard_equal(model.weight.grad, weight.grad, pg.tp_local_rank(), pg.tp_world_size())


def run_dist(rank, world_size, port):
    # config = dict(parallel=dict(tensor=dict(mode="1d", size=world_size),))
    colossalai.launch(config={}, rank=rank, world_size=world_size, host='localhost', port=port, backend='nccl')
    pg = ProcessGroup(tp_degree=world_size)
    run_with_spec(init_1d_row, pg)
    run_with_spec(init_1d_col, pg)


@pytest.mark.dist
@pytest.mark.parametrize('world_size', [1, 4])
@rerun_if_address_is_in_use()
def test_embedding_1d(world_size):
    run_func = partial(run_dist, world_size=world_size, port=free_port())
    mp.spawn(run_func, nprocs=world_size)


if __name__ == '__main__':
    test_embedding_1d(4)
