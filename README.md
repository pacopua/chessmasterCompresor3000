# chessmasterCompresor3000

## Requisitos

El ejecutable requiere tener **Python 3.9 o superior** instalado, junto con las siguientes librerías:

```bash
pip install chess bitarray numpy
```

## Instrucciones de uso

Si el ejecutable no tiene permisos de ejecución (puede ocurrir al descomprimir un zip), ejecutar primero:

```bash
chmod +x compress.cdi
```

Luego:

```bash
./compress.cdi <infile> <outfile>
```

El programa detecta automáticamente si ha de comprimir o descomprimir leyendo los 4 primeros bytes de `infile`. Si encuentra la cabecera `CPG5` (cabecera específica de nuestro compresor), descomprime el archivo. En caso contrario, comprime.