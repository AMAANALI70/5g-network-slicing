import pandas as pd
import matplotlib.pyplot as plt
import time

plt.ion()

while True:
    try:
        df = pd.read_csv("experiment_data.csv")
        plt.clf()

        plt.subplot(3,1,1)
        plt.plot(df["embb_throughput"])
        plt.title("eMBB Throughput")

        plt.subplot(3,1,2)
        plt.plot(df["urllc_rtt"])
        plt.title("URLLC RTT")

        plt.subplot(3,1,3)
        plt.plot(df["node_cpu"])
        plt.title("Node CPU Utilization")

        plt.tight_layout()
        plt.pause(5)
    except:
        pass