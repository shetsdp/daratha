import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

# 1. Mocking a 15x15 core lattice flux output matrix for visualization
# In reality, you would load your actual simulation output file here
np.random.seed(42)
core_dimension = 15
# Simulating a typical peak-in-the-center cosine flux profile of a reactor
x, y = np.meshgrid(np.linspace(-1, 1, core_dimension), np.linspace(-1, 1, core_dimension))
dst = np.sqrt(x**2 + y**2)
flux_matrix = np.cos(dst * (np.pi / 2.5)) * 1e14  # Typical power reactor flux magnitude (n/cm^2-s)

# 2. Plotting the 2D Flux Map Heatmap
plt.figure(figsize=(8, 6))
ax = sns.heatmap(
    flux_matrix, 
    cmap="inferno",       # 'inferno' or 'jet' are standard for nuclear thermal/flux gradients
    annot=False,          # Set to True if you want to see exact numerical values in each cell
    square=True, 
    cbar_kws={'label': 'Neutron Flux ($\phi$) [n/cm²·s]'}
)

plt.title("2D Reactor Core Neutron Flux Distribution Map ($X-Y$ Plane)")
plt.xlabel("Lattice X-Position (Column)")
plt.ylabel("Lattice Y-Position (Row)")
plt.show()
