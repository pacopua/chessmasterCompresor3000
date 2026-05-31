# chessmasterCompresor3000

## Requisitos para compilar

El código hecho en python se ha convertido en un único ejecutable utilizando `PyInstaller`. Esto significa que no hay ningún requisito en específico para poder ejecutar la aplicación! No se ha de tener python instalado siquiera, puesto que `PyInstaller` comprime un entorno de python con todo lo necesario para ejecutar el código.

## Instrucciones de uso

Como especifica el PDF de la practica, el ejecutable se ejecuta de la siguiente forma:
```bash
user@host> compress.cdi <infile> <outfile>
```

En la linea de comandos

La forma en que el código detecta si ha de codificar o decodificar es leyendo los 4 primeros carácteres del archivo `infile`. Hemos hecho que nuestro codificador escriba CPG5 (5 es el número de la iteración de nuestra implementación) en los primeros 4 bytes del binario comprimido. De esta forma, si el programa lee CPG5, sabrá que tiene que descomprimir, en caso contrario, sabrá que ha de comprimir.