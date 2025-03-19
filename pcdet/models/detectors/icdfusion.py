from .detector3d_template import Detector3DTemplate
from .. import backbones_image, view_transforms, teacher
from ..backbones_image import img_neck
from ..backbones_2d import fuser


class ICDFusion_kitti(Detector3DTemplate):
    def __init__(self, model_cfg, num_class, dataset):
        super().__init__(model_cfg=model_cfg, num_class=num_class, dataset=dataset)
        self.module_topology = [
            'vfe', 'backbone_3d', 'teacher', 'map_to_bev_module', 'pfe',
            'image_backbone', 'neck', 'vtransform', 'fuser',
            'backbone_2d', 'dense_head', 'point_head', 'roi_head'
        ]
        self.module_list = self.build_networks()

    def build_teacher(self, model_info_dict):
        if self.model_cfg.get('TEACHER', None) is None:
            return None, model_info_dict
        teacher_module = teacher.__all__[self.model_cfg.TEACHER.NAME](
            model_cfg=self.model_cfg.TEACHER,
            input_channels=model_info_dict['num_rawpoint_features'],
            grid_size=model_info_dict['grid_size'],
        )
        model_info_dict['module_list'].append(teacher_module)
        return teacher_module, model_info_dict

    def build_neck(self, model_info_dict):
        if self.model_cfg.get('NECK', None) is None:
            return None, model_info_dict
        neck_module = img_neck.__all__[self.model_cfg.NECK.NAME](
            model_cfg=self.model_cfg.NECK
        )
        model_info_dict['module_list'].append(neck_module)

        return neck_module, model_info_dict

    def build_vtransform(self, model_info_dict):
        if self.model_cfg.get('VTRANSFORM', None) is None:
            return None, model_info_dict

        vtransform_module = view_transforms.__all__[self.model_cfg.VTRANSFORM.NAME](
            model_cfg=self.model_cfg.VTRANSFORM
        )
        model_info_dict['module_list'].append(vtransform_module)

        return vtransform_module, model_info_dict

    def build_image_backbone(self, model_info_dict):
        if self.model_cfg.get('IMAGE_BACKBONE', None) is None:
            return None, model_info_dict
        image_backbone_module = backbones_image.__all__[self.model_cfg.IMAGE_BACKBONE.NAME](
            model_cfg=self.model_cfg.IMAGE_BACKBONE
        )
        image_backbone_module.init_weights()
        model_info_dict['module_list'].append(image_backbone_module)

        return image_backbone_module, model_info_dict

    def build_fuser(self, model_info_dict):
        if self.model_cfg.get('FUSER', None) is None:
            return None, model_info_dict

        fuser_module = fuser.__all__[self.model_cfg.FUSER.NAME](
            model_cfg=self.model_cfg.FUSER
        )
        model_info_dict['module_list'].append(fuser_module)
        model_info_dict['num_bev_features'] = self.model_cfg.FUSER.OUT_CHANNEL
        return fuser_module, model_info_dict

    def forward(self, batch_dict):

        # for i,cur_module in enumerate(self.module_list):
        #     batch_dict = cur_module(batch_dict)
        for i, cur_module in enumerate(self.module_list):
            batch_dict = cur_module(batch_dict)

        if self.training:
            loss, tb_dict, disp_dict = self.get_training_loss()

            ret_dict = {
                'loss': loss
            }
            return ret_dict, tb_dict, disp_dict
        else:
            pred_dicts, recall_dicts = self.post_processing(batch_dict)
            return pred_dicts, recall_dicts

    # single-stage
    # def get_training_loss(self,batch_dict):
    #     disp_dict = {}

    #     loss_rpn, tb_dict = self.dense_head.get_loss()
    #     tb_dict = {
    #         'loss_rpn': loss_rpn.item(),
    #         **tb_dict
    #     }

    #     loss = loss_rpn
    #     return loss, tb_dict, disp_dict

    # two-stage
    def get_training_loss(self):
        disp_dict = {}
        loss = 0

        loss_rpn, tb_dict = self.dense_head.get_loss()
        loss_rcnn, tb_dict = self.roi_head.get_loss(tb_dict)

        loss = loss + loss_rpn + loss_rcnn

        if hasattr(self.backbone_3d, 'get_loss'):
            loss_backbone3d, tb_dict = self.backbone_3d.get_loss(tb_dict)
            loss += loss_backbone3d
        if hasattr(self.vtransform, 'get_loss'):
            loss_vtrans, tb_dict = self.vtransform.get_loss(tb_dict)
            loss += loss_vtrans
        return loss, tb_dict, disp_dict