# Extracted from seeg_decode eafcdc9, algorithm/model.py.
# Classroom adaptation: keep every sensor dimension, including one/two-channel EMG.
import torch.nn as nn

class LiteCNN1D(nn.Module):
    def __init__(self, num_channels, num_times, num_classes):
        super().__init__()
        # Do not force two independent muscles into a single mixture before
        # nonlinear features can distinguish one muscle from both muscles.
        self.channel_projection = nn.Conv1d(num_channels, num_channels, kernel_size=1)
        self.conv1 = nn.Sequential(
            nn.Conv1d(num_channels, 16, kernel_size=1),
            nn.GroupNorm(4, 16),
            nn.Mish(),
            nn.MaxPool1d(2, stride=2),
            nn.Dropout(0.1)
        )
        # 空洞卷积块
        self.conv2 = nn.Sequential(
            nn.Conv1d(16, 32, kernel_size=3, padding=2, dilation=2),
            nn.GroupNorm(4, 32),
            nn.Mish(),
            nn.MaxPool1d(2, stride=2),
            nn.Dropout(0.1)
        )
        # 分类头
        self.fc = nn.Linear(32, num_classes)

    def forward(self, x):
        x = self.channel_projection(x)
        x = self.conv1(x)
        x = self.conv2(x)
        x = x.mean(dim=-1)  # 全局平均池化
        return self.fc(x)
