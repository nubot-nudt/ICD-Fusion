import torch

from . import bev_pool_ext

__all__ = ["bev_pool"]


class QuickCumsum(torch.autograd.Function):
    @staticmethod
    def forward(ctx, x, geom_feats, ranks):
        x = x.cumsum(0)
        kept = torch.ones(x.shape[0], device=x.device, dtype=torch.bool)
        kept[:-1] = ranks[1:] != ranks[:-1]

        x, geom_feats = x[kept], geom_feats[kept]
        x = torch.cat((x[:1], x[1:] - x[:-1]))

        # save kept for backward
        ctx.save_for_backward(kept)

        # no gradient for geom_feats
        ctx.mark_non_differentiable(geom_feats)

        return x, geom_feats

    @staticmethod
    def backward(ctx, gradx, gradgeom):
        (kept,) = ctx.saved_tensors
        back = torch.cumsum(kept, 0)
        back[kept] -= 1

        val = gradx[back]

        return val, None, None


class QuickCumsumCuda(torch.autograd.Function):
    @staticmethod
    def forward(ctx, x, geom_feats, ranks, B, D, H, W):
        kept = torch.ones(x.shape[0], device=x.device, dtype=torch.bool)
        kept[1:] = ranks[1:] != ranks[:-1]
        interval_starts = torch.where(kept)[0].int()
        interval_lengths = torch.zeros_like(interval_starts)
        interval_lengths[:-1] = interval_starts[1:] - interval_starts[:-1]
        interval_lengths[-1] = x.shape[0] - interval_starts[-1]
        geom_feats = geom_feats.int()

        out = bev_pool_ext.bev_pool_forward(
            x,
            geom_feats,
            interval_lengths,
            interval_starts,
            B,
            D,
            H,
            W,
        )

        ctx.save_for_backward(interval_starts, interval_lengths, geom_feats)
        # ctx.saved_shapes=torch.tensor([B, D, H, W], device=x.device)
        ctx.saved_shapes = B, D, H, W
        return out

    @staticmethod
    def backward(ctx, out_grad):
        interval_starts, interval_lengths, geom_feats = ctx.saved_tensors
        B, D, H, W = ctx.saved_shapes
        # B, D, H, W = ctx.saved_shapes.tolist()
        out_grad = out_grad.contiguous()
        x_grad = bev_pool_ext.bev_pool_backward(
            out_grad,
            geom_feats,
            interval_lengths,
            interval_starts,
            B,
            D,
            H,
            W,
        )

        return x_grad, None, None, None, None, None, None


def bev_pool(feats, coords, B, D, H, W):
    assert feats.shape[0] == coords.shape[0]
    '''
    将3D特征聚合到BEV空间中
    Args:
        feats: (B * D * H * W, C)
        coords: (B * D * H * W, 4)| X,Y,Z,batch_idx
        B: batch size
        D: depth size
        H: height size
        W: width size
    Returns:
        x: (B, C, D, H, W)
    '''
    ranks = (
        coords[:, 0] * (W * D * B)
        + coords[:, 1] * (D * B)
        + coords[:, 2] * B
        + coords[:, 3]
    )
    indices = ranks.argsort()   # 默认从小到大排序
    feats, coords, ranks = feats[indices], coords[indices], ranks[indices]

    # 实现在给定排序下，对feats进行累加求和
    x = QuickCumsumCuda.apply(feats, coords, ranks, B, D, H, W)
    x = x.permute(0, 4, 1, 2, 3).contiguous() # （B, C, D, H, W）
    return x
